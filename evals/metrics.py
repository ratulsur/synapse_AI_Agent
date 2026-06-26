"""Eval metrics for the Synapse research-report pipeline.

All metric functions are pure / deterministic and take typed objects from
the pipeline (GraphState fields).  They do NOT make LLM calls; the optional
LLM-judge groundedness check lives in harness.py and is live-only.

Metrics
-------
report_completeness     -- Fraction of plan sections that are non-empty in
                           the final output (0..1).
routing_accuracy        -- Whether the active_domains overlap with the query's
                           expected domains (binary per query, averaged across
                           the dataset).
groundedness_simple     -- For each section, fraction of cited_source_ids that
                           resolve to an actual saved source id.  Averaged
                           across sections.  Does NOT judge claim-level truth;
                           that requires the LLM grader.
source_diversity        -- Fraction of sections where cited sources span more
                           than one distinct tool or domain (proxy for
                           breadth of evidence).
iteration_counts        -- Returns the retrieval and revise iteration counts
                           from state (reported for observability; no threshold).

Threshold constants (MUST_PASS dict) define the gating values for the eval
harness.  Justification for each threshold lives inline.

Owner: Ratul Sur
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.section import Section
    from schemas.source import Source

# ---------------------------------------------------------------------------
# Threshold constants
# These are the gating thresholds used by the eval harness.
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, float] = {
    # All plan sections must be populated with non-empty content.
    # A partially-assembled report is functionally unusable; 0.9 allows for
    # a single empty section out of ten, but with only 3 canonical sections
    # the effective minimum is 2/3 (a full pass requires 3/3 = 1.0 in practice).
    "report_completeness": 0.9,

    # The router must assign at least one correct domain per query.
    # 0.7 = 4 out of 6 queries routed correctly.  Some multi-domain queries
    # may legitimately route to a different-but-valid label (e.g. GENERIC
    # for the AI/healthcare query), so a relaxed threshold is appropriate.
    "routing_accuracy": 0.70,

    # Every cited source_id must resolve to a saved source.
    # 0.8 = at most 1 in 5 citations may be phantom/fabricated ids.
    # This is weaker than claim-level groundedness (which needs an LLM judge)
    # but catches obvious hallucinated citations.
    "groundedness_simple": 0.80,

    # At least half the evaluated queries must produce multi-source evidence.
    # 0.5 is lenient because source diversity depends heavily on the query
    # domain and available tool coverage, not just the routing logic.
    "source_diversity": 0.50,
}


# ---------------------------------------------------------------------------
# report_completeness
# ---------------------------------------------------------------------------


def report_completeness(sections: "list[Section]", plan_section_count: int) -> float:
    """Return the fraction of expected sections that have non-empty content.

    Args:
        sections:            The list of Section objects from final state.
        plan_section_count:  Number of SectionSpecs in the approved plan.
                             Used as the denominator; avoids penalising when
                             the writer correctly maps all specs.

    Returns:
        float in [0, 1].  1.0 means every expected section is non-empty.
    """
    if plan_section_count <= 0:
        return 1.0  # no sections expected -> vacuously complete
    drafted_non_empty = sum(1 for s in sections if s.content.strip())
    return min(drafted_non_empty / plan_section_count, 1.0)


# ---------------------------------------------------------------------------
# routing_accuracy
# ---------------------------------------------------------------------------


def routing_accuracy(
    expected_domains: list[str],
    active_domains: list[str],
) -> float:
    """Check whether the router's active_domains overlaps with expected_domains.

    Uses a simple hit/miss binary (1.0 if any expected domain appears in
    active_domains, 0.0 otherwise).  Call this per query and average the
    results across the dataset.

    Args:
        expected_domains: The expected routing labels from the eval dataset.
        active_domains:   The actual active_domains set by the query_router node.

    Returns:
        1.0 (hit) or 0.0 (miss).
    """
    if not expected_domains:
        return 1.0  # no expectation -> vacuously correct
    active_set = set(active_domains or [])
    expected_set = set(expected_domains)
    return 1.0 if active_set & expected_set else 0.0


# ---------------------------------------------------------------------------
# groundedness_simple (citation resolution check)
# ---------------------------------------------------------------------------


def groundedness_simple(
    sections: "list[Section]",
    sources: "list[Source]",
) -> float:
    """Fraction of cited source_ids that resolve to a saved source.

    For each section, counts how many of its cited_source_ids appear in the
    saved sources pool.  Averages per-section scores across all sections with
    at least one citation.

    Note: this is NOT claim-level groundedness -- it only verifies that the
    ids cited by writers actually correspond to retrieved sources.  The live
    LLM-judge check in harness.py is the real groundedness measure.

    Args:
        sections: Section objects (with cited_source_ids populated).
        sources:  The full Source pool from state.

    Returns:
        float in [0, 1].  1.0 means all cited ids resolve to real sources.
        Returns 1.0 if no sections cite any sources (vacuously grounded).
    """
    all_source_ids: set[str] = {s.id for s in sources}
    section_scores: list[float] = []
    for sec in sections:
        cited = sec.cited_source_ids or []
        if not cited:
            continue  # skip sections with no citations (don't penalise stubs)
        resolvable = sum(1 for cid in cited if cid in all_source_ids)
        section_scores.append(resolvable / len(cited))
    if not section_scores:
        return 1.0
    return sum(section_scores) / len(section_scores)


# ---------------------------------------------------------------------------
# source_diversity
# ---------------------------------------------------------------------------


def source_diversity(
    sections: "list[Section]",
    sources: "list[Source]",
) -> float:
    """Proxy for breadth of evidence: fraction of sections with multi-source citations.

    A section is 'diverse' if its cited sources span more than one distinct
    (tool, domain) pair.

    Args:
        sections: Section objects.
        sources:  The full Source pool.

    Returns:
        float in [0, 1].  1.0 means every cited section has multi-source evidence.
        Returns 1.0 if no sections cite anything (vacuously diverse).
    """
    by_id: dict[str, "Source"] = {s.id: s for s in sources}
    diverse_count = 0
    cited_section_count = 0
    for sec in sections:
        cited_ids = sec.cited_source_ids or []
        if not cited_ids:
            continue
        cited_section_count += 1
        pairs: set[tuple[str | None, str]] = set()
        for cid in cited_ids:
            src = by_id.get(cid)
            if src:
                pairs.add((src.tool, src.domain))
        if len(pairs) > 1:
            diverse_count += 1
    if cited_section_count == 0:
        return 1.0
    return diverse_count / cited_section_count


# ---------------------------------------------------------------------------
# iteration_counts (observability only, no threshold)
# ---------------------------------------------------------------------------


def iteration_counts(state: dict) -> dict[str, int]:
    """Extract loop iteration counts from the final graph state.

    Returns a dict with 'retrieval_iteration' and 'revise_iteration' keys
    for logging / reporting.  No threshold is enforced.

    Args:
        state: The final GraphState (or any dict with the relevant keys).

    Returns:
        {"retrieval_iteration": int, "revise_iteration": int}
    """
    return {
        "retrieval_iteration": state.get("retrieval_iteration", 0),
        "revise_iteration": state.get("revise_iteration", 0),
    }


# ---------------------------------------------------------------------------
# dataset_pass
# ---------------------------------------------------------------------------


def compute_dataset_metrics(results: list[dict]) -> dict[str, float]:
    """Aggregate per-query result dicts into dataset-level metric averages.

    Each element of ``results`` is the dict returned by harness.py's
    ``_evaluate_one()`` function.

    Returns a dict of metric_name -> average_score.
    """
    if not results:
        return {}

    keys = [
        "completeness",
        "routing_accuracy",
        "groundedness_simple",
        "source_diversity",
    ]
    totals: dict[str, float] = {k: 0.0 for k in keys}
    for r in results:
        for k in keys:
            totals[k] += r.get(k, 0.0)
    n = len(results)
    return {k: totals[k] / n for k in keys}


def passes_thresholds(metrics: dict[str, float]) -> tuple[bool, list[str]]:
    """Return (overall_pass, list_of_failing_metric_names).

    Args:
        metrics: Output of compute_dataset_metrics().

    Returns:
        (True, []) if all gated metrics meet their thresholds;
        (False, [failing_metric, ...]) otherwise.
    """
    failures: list[str] = []
    gated_keys = ["completeness", "routing_accuracy", "groundedness_simple"]
    threshold_map = {
        "completeness": THRESHOLDS["report_completeness"],
        "routing_accuracy": THRESHOLDS["routing_accuracy"],
        "groundedness_simple": THRESHOLDS["groundedness_simple"],
    }
    for key in gated_keys:
        threshold = threshold_map.get(key, 0.0)
        actual = metrics.get(key, 0.0)
        if actual < threshold:
            failures.append(f"{key}={actual:.3f} (threshold={threshold:.3f})")
    return (len(failures) == 0, failures)
