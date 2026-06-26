"""Node: Final Answer.

Terminal node before END.  Packages the assembled report plus run metadata
(sources used, low_confidence flag, iteration counts) into ``final_answer``
as a JSON string for return to the caller / API layer.

This is a purely deterministic node -- no LLM call.

Owner: Ratul Sur
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log


def final_answer(state: GraphState) -> dict:
    """Package the report and run metadata into the terminal payload.

    Returns a partial state update with key:
        final_answer  -- str (JSON-encoded result envelope)
    """
    try:
        report: str = state.get("report") or ""
        sources = state.get("sources") or []
        sections = state.get("sections") or []

        metadata: dict = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "low_confidence": state.get("low_confidence", False),
            "retrieval_iteration": state.get("retrieval_iteration", 0),
            "max_retrieval_iterations": state.get("max_retrieval_iterations", 3),
            "revise_iteration": state.get("revise_iteration", 0),
            "max_revise_iterations": state.get("max_revise_iterations", 2),
            "source_count": len(sources),
            "section_count": len(sections),
            "active_domains": state.get("active_domains") or [],
            "source_ids": [s.id for s in sources],
        }

        grounding_grade = state.get("grounding_grade")
        if grounding_grade:
            metadata["grounding_score"] = grounding_grade.score
            metadata["grounding_passed"] = grounding_grade.passed

        source_grade = state.get("source_grade")
        if source_grade:
            metadata["source_grade_score"] = source_grade.score
            metadata["source_grade_passed"] = source_grade.passed

        payload: dict = {
            "query": state.get("query", ""),
            "report": report,
            "metadata": metadata,
        }

        answer_str: str = json.dumps(payload, indent=2, default=str)

        log.info(
            "final_answer: terminal payload assembled",
            char_count=len(report),
            source_count=len(sources),
            low_confidence=metadata["low_confidence"],
        )

        return {"final_answer": answer_str}

    except Exception as exc:
        msg = "final_answer node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
