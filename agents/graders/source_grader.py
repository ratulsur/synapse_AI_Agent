"""Grader: Source Grader (LLM judge over collected evidence).

Judges whether the accumulated, deduped ``Source[]`` is sufficient and relevant
to satisfy the plan. On a NO verdict it also selects a ``MutationAction``
(reformulate / widen / reroute) that the retrieval loop applies on its next
iteration -- this is the retry-mutation strategy that makes the NO edge do real
work instead of re-running the same failing path.

Signature (called by graph.subgraphs.retrieval_evidence):
    run_source_grader(state) -> GraderVerdict

Prompt: prompts.templates.SOURCE_GRADER_SYSTEM / SOURCE_GRADER_USER.
Rubric: prompts/rubrics/source_grader_rubric.md (injected into the system prompt).

Termination note: this grader never reads/writes the iteration counter -- the
subgraph increments ``retrieval_iteration`` and the ``route_after_source_grader``
edge enforces the cap. The grader only judges quality and proposes the mutation.

Owner: agent-prompt-engineer
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agents._common import format_plan, format_sources, get_llm, load_rubric
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import (
    PROMPT_VERSIONS,
    SOURCE_GRADER_SYSTEM,
    SOURCE_GRADER_USER,
)
from schemas.grading import GraderVerdict, MutationAction
from schemas.source import Source

_RUBRIC_FILE = "source_grader_rubric.md"


def run_source_grader(state: GraphState) -> GraderVerdict:
    """Judge evidence sufficiency/relevance and propose a mutation on failure.

    Args:
        state: GraphState; reads ``query``, ``plan``, ``sources``,
               ``active_domains``, iteration counters.

    Returns:
        GraderVerdict: passed / score / rationale / mutation_action.
    """
    try:
        query: str = state.get("query", "")
        plan = state.get("plan")
        sources: list[Source] = state.get("sources") or []
        active_domains: list[str] = state.get("active_domains") or ["GENERIC"]
        iteration: int = state.get("retrieval_iteration", 0) + 1
        max_iterations: int = state.get("max_retrieval_iterations", 3)

        log.info(
            "run_source_grader: grading evidence",
            prompt_version=PROMPT_VERSIONS["source_grader"],
            source_count=len(sources),
            iteration=iteration,
            max_iterations=max_iterations,
        )

        # Empty pool short-circuit: nothing to grade -> fail + widen (need more).
        if not sources:
            verdict = GraderVerdict(
                passed=False,
                score=0.0,
                rationale="No sources were retrieved; cannot satisfy any section of the plan.",
                mutation_action=MutationAction.WIDEN,
            )
            log.info("run_source_grader: empty pool -> fail/widen")
            return verdict

        llm = get_llm().with_structured_output(GraderVerdict)
        messages = [
            SystemMessage(
                content=SOURCE_GRADER_SYSTEM.format(rubric=load_rubric(_RUBRIC_FILE))
            ),
            HumanMessage(
                content=SOURCE_GRADER_USER.format(
                    query=query,
                    plan=format_plan(plan),
                    active_domains=", ".join(active_domains),
                    iteration=iteration,
                    max_iterations=max_iterations,
                    source_count=len(sources),
                    sources=format_sources(sources),
                )
            ),
        ]
        verdict: GraderVerdict = llm.invoke(messages)

        verdict = _enforce_invariants(verdict)

        log.info(
            "run_source_grader: verdict",
            passed=verdict.passed,
            score=verdict.score,
            mutation_action=verdict.mutation_action.value if verdict.mutation_action else None,
        )
        return verdict

    except Exception as exc:
        msg = "run_source_grader agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _enforce_invariants(verdict: GraderVerdict) -> GraderVerdict:
    """Keep the verdict self-consistent for the retrieval router.

    * On PASS: clear any mutation_action (not used on the pass edge).
    * On FAIL: guarantee a mutation_action so the loop has a concrete strategy;
      default to REFORMULATE when the model omitted one.
    """
    if verdict.passed:
        if verdict.mutation_action is not None:
            verdict.mutation_action = None
    else:
        if verdict.mutation_action is None:
            log.warning("run_source_grader: fail with no mutation_action, defaulting REFORMULATE")
            verdict.mutation_action = MutationAction.REFORMULATE
    return verdict
