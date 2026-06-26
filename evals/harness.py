"""Eval harness: runs the graph over the graded dataset and scores quality + groundedness.

LIVE MODE GATE
--------------
This harness makes REAL calls to LLMs and search APIs.  It is deliberately
opt-in so CI runs never hit the network or require API keys.

Opt-in:
    RUN_LIVE_EVALS=1 venv/bin/python -m evals.harness [--provider groq|openai]

When RUN_LIVE_EVALS is absent or 0, the harness prints a skip message and
exits 0 (clean skip -- does not fail CI).

API-key gate:
    The harness checks that at least one of OPENAI_API_KEY or GROQ_API_KEY is
    set before running.  GOOGLE_API_KEY is NOT used as a default because the
    account is out of credits (429).

Default provider: groq (fast + inexpensive for evals); override with
    --provider openai

Scoring
-------
Each query in evals/datasets/queries.json is run through the full graph
(create_analyst -> ... -> final_answer) with a real LLM.  Per-query metrics:
  - completeness:       fraction of non-empty sections.
  - routing_accuracy:   router matched expected domains.
  - groundedness_simple: cited source ids resolve to saved sources.
  - source_diversity:   sections cite sources from multiple tools/domains.

Dataset metrics are averaged across queries and checked against the thresholds
defined in evals/metrics.py.  The harness exits 0 on pass, 1 on failure.

Usage:
    RUN_LIVE_EVALS=1 venv/bin/python -m evals.harness
    RUN_LIVE_EVALS=1 venv/bin/python -m evals.harness --provider openai

Owner: Ratul Sur
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Guards (pure functions, no side effects at import time)
# ---------------------------------------------------------------------------


def _is_live() -> bool:
    """Return True when RUN_LIVE_EVALS env var is set to a truthy value."""
    return os.environ.get("RUN_LIVE_EVALS", "0").strip() not in ("", "0", "false", "False")


def _check_api_keys(provider: str) -> bool:
    """Return True if the required API key is present for the selected provider."""
    key_map = {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_key = key_map.get(provider)
    if env_key and os.environ.get(env_key):
        return True
    # Fallback: check any of the non-google keys
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY"):
        return True
    return False


def _load_dataset() -> list[dict]:
    """Load the graded query set from evals/datasets/queries.json."""
    dataset_path = Path(__file__).resolve().parent / "datasets" / "queries.json"
    if not dataset_path.exists():
        print(f"[evals.harness] ERROR: dataset not found at {dataset_path}", file=sys.stderr)
        sys.exit(1)
    with dataset_path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Per-query evaluation
# ---------------------------------------------------------------------------


def _evaluate_one(entry: dict, graph: Any, provider: str) -> dict:
    """Run one query through the full graph and compute per-query metrics.

    Returns a dict with keys: id, query, completeness, routing_accuracy,
    groundedness_simple, source_diversity, retrieval_iteration, revise_iteration,
    error (if any).
    """
    from langgraph.types import Command

    from evals.metrics import (
        groundedness_simple,
        iteration_counts,
        report_completeness,
        routing_accuracy,
        source_diversity,
    )

    query_id = entry["id"]
    query = entry["query"]
    expected_domains = entry.get("expected_domains", [])
    plan_section_count = entry.get("plan_section_count", 3)  # default 3-section plan

    tid = f"eval-{query_id}-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": tid}}

    result: dict = {
        "id": query_id,
        "query": query,
        "completeness": 0.0,
        "routing_accuracy": 0.0,
        "groundedness_simple": 0.0,
        "source_diversity": 0.0,
        "retrieval_iteration": 0,
        "revise_iteration": 0,
        "error": None,
    }

    try:
        # Phase 1: run until HITL interrupt
        state1 = graph.invoke({"query": query}, cfg)
        if "__interrupt__" not in state1:
            result["error"] = "Expected HITL interrupt but none fired"
            return result

        # Phase 2: auto-approve the plan (eval harness skips human review)
        final_state = graph.invoke(Command(resume={"approved": True}), cfg)

        # Collect typed objects
        sections = final_state.get("sections") or []
        sources = final_state.get("sources") or []
        active_domains = final_state.get("active_domains") or []
        plan = final_state.get("plan")

        n_plan_sections = len(plan.sections) if plan else plan_section_count

        # Compute metrics
        result["completeness"] = report_completeness(sections, n_plan_sections)
        result["routing_accuracy"] = routing_accuracy(expected_domains, active_domains)
        result["groundedness_simple"] = groundedness_simple(sections, sources)
        result["source_diversity"] = source_diversity(sections, sources)
        iters = iteration_counts(final_state)
        result["retrieval_iteration"] = iters["retrieval_iteration"]
        result["revise_iteration"] = iters["revise_iteration"]
        result["low_confidence"] = final_state.get("low_confidence", False)

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    return result


# ---------------------------------------------------------------------------
# Main harness entry point
# ---------------------------------------------------------------------------


def run_eval(provider: str = "groq") -> int:
    """Run the eval harness.  Returns 0 on pass, 1 on failure.

    This function is the public API; it does NOT call sys.exit() -- that is
    left to the CLI wrapper so callers can inspect the return code.
    """
    from evals.metrics import THRESHOLDS, compute_dataset_metrics, passes_thresholds

    print(f"\n[evals.harness] Starting live eval run (provider={provider})")

    # API key check
    if not _check_api_keys(provider):
        print(
            f"[evals.harness] ERROR: no API key found for provider '{provider}'.\n"
            "  Set GROQ_API_KEY or OPENAI_API_KEY in the environment.",
            file=sys.stderr,
        )
        return 1

    # Set the LLM provider env var for ModelLoader
    os.environ["LLM_PROVIDER"] = provider
    print(f"[evals.harness] LLM_PROVIDER set to '{provider}'")

    # Load dataset
    dataset = _load_dataset()
    print(f"[evals.harness] Dataset loaded: {len(dataset)} queries")

    # Build the graph ONCE (MemorySaver checkpointer; each query gets its own thread_id)
    from graph.builder import build_graph
    graph = build_graph()
    print("[evals.harness] Graph compiled successfully")

    # Run each query
    per_query_results: list[dict] = []
    for i, entry in enumerate(dataset, 1):
        qid = entry["id"]
        print(f"\n[evals.harness] [{i}/{len(dataset)}] Running query: {qid!r}")
        print(f"  query: {entry['query'][:80]}")
        result = _evaluate_one(entry, graph, provider)
        per_query_results.append(result)

        if result.get("error"):
            print(f"  ERROR: {result['error']}")
        else:
            print(
                f"  completeness={result['completeness']:.2f}  "
                f"routing={result['routing_accuracy']:.2f}  "
                f"groundedness={result['groundedness_simple']:.2f}  "
                f"diversity={result['source_diversity']:.2f}  "
                f"retrieval_iter={result['retrieval_iteration']}  "
                f"revise_iter={result['revise_iteration']}  "
                f"low_conf={result.get('low_confidence', False)}"
            )

    # Aggregate
    print("\n" + "=" * 70)
    print("[evals.harness] DATASET SUMMARY")
    print("=" * 70)

    dataset_metrics = compute_dataset_metrics(per_query_results)
    threshold_key_map = {
        "completeness": "report_completeness",
        "routing_accuracy": "routing_accuracy",
        "groundedness_simple": "groundedness_simple",
        "source_diversity": "source_diversity",
    }
    for metric, value in dataset_metrics.items():
        tk = threshold_key_map.get(metric, metric)
        threshold = THRESHOLDS.get(tk)
        threshold_str = f"  (threshold >= {threshold:.2f})" if threshold is not None else ""
        print(f"  {metric:<25} {value:.3f}{threshold_str}")

    errors = [r for r in per_query_results if r.get("error")]
    if errors:
        print(f"\n  Queries with errors: {len(errors)}")
        for r in errors:
            print(f"    [{r['id']}] {r['error']}")

    overall_pass, failures = passes_thresholds(dataset_metrics)
    print()
    if overall_pass:
        print("[evals.harness] PASS -- all gated metrics meet thresholds")
        return 0
    else:
        print("[evals.harness] FAIL -- the following metrics are below threshold:")
        for f in failures:
            print(f"  {f}")
        return 1


# ---------------------------------------------------------------------------
# CLI entry point  (executed only via `python -m evals.harness`)
# ---------------------------------------------------------------------------


def _cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="Synapse AI Agent -- eval harness (live, opt-in via RUN_LIVE_EVALS=1)"
    )
    parser.add_argument(
        "--provider",
        choices=["groq", "openai"],
        default="groq",
        help="LLM provider to use (default: groq).  Do not default to google (out of credits).",
    )
    args = parser.parse_args()

    # Live gate check -- only here, at execution time, not at import time.
    if not _is_live():
        print(
            "\n[evals.harness] Skipping live evals -- set RUN_LIVE_EVALS=1 to run.\n"
            "  Example:\n"
            "    RUN_LIVE_EVALS=1 venv/bin/python -m evals.harness\n"
            "    RUN_LIVE_EVALS=1 venv/bin/python -m evals.harness --provider openai\n"
        )
        sys.exit(0)

    sys.exit(run_eval(provider=args.provider))


if __name__ == "__main__":
    _cli()
