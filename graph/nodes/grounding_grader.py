"""Node: Grounding Grader.

LLM-judge node that verifies every drafted section's claims against its cited
sources.  Returns a ``GraderVerdict`` that includes ``failing_section_ids``
(sections whose claims are not fully supported by their sources).

The conditional edge ``route_after_grounding_grader`` reads this verdict to
decide between ``revise_section`` and ``assemble_report``.

Delegates to ``agents.graders.grounding_grader``; falls back to a passing
verdict when the stub is not yet implemented so the graph can reach
``assemble_report`` end-to-end.

Owner: Ratul Sur
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.grading import GraderVerdict


def grounding_grader(state: GraphState) -> dict:
    """Grade all drafted sections for grounding.

    Returns a partial state update with key:
        grounding_grade  -- GraderVerdict
    """
    try:
        sections = state.get("sections") or []
        sources = state.get("sources") or []
        log.info(
            "grounding_grader: evaluating sections",
            section_count=len(sections),
            source_count=len(sources),
        )

        # --- Delegate to agent stub ---
        try:
            from agents.graders.grounding_grader import run_grounding_grader  # type: ignore[import]
            verdict: GraderVerdict = run_grounding_grader(state)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug(
                "grounding_grader: agent stub not ready, returning stub passing verdict"
            )
            # All sections are treated as grounded so the graph can proceed.
            verdict = GraderVerdict(
                passed=True,
                score=1.0,
                rationale="Stub: grounding grader agent not yet implemented.",
                failing_section_ids=[],
            )

        log.info(
            "grounding_grader: verdict",
            passed=verdict.passed,
            score=verdict.score,
            failing_section_ids=verdict.failing_section_ids,
        )

        return {"grounding_grade": verdict}

    except Exception as exc:
        msg = "grounding_grader node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
