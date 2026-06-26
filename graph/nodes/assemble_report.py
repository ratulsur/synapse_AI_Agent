"""Node: Assemble Report.

Pure-function (deterministic) node that joins grounded sections in plan order
into a single report string.  No LLM call.

Format:
    ## <heading>

    <content>

    [Sources: source_id_1, source_id_2]

Owner: Ratul Sur
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.plan import ReportPlan
from schemas.section import Section


def assemble_report(state: GraphState) -> dict:
    """Join grounded sections in plan order into a report string.

    Returns a partial state update with key:
        report  -- str
    """
    try:
        sections: list[Section] = state.get("sections") or []
        plan: ReportPlan | None = state.get("plan")
        low_confidence: bool = state.get("low_confidence", False)

        if not sections:
            log.warning("assemble_report: no sections to assemble")
            return {"report": ""}

        # Determine section order from the plan if available.
        if plan:
            spec_order: dict[str, int] = {s.id: s.order for s in plan.sections}
        else:
            spec_order = {s.spec_id: idx for idx, s in enumerate(sections)}

        sorted_sections = sorted(
            sections,
            key=lambda s: spec_order.get(s.spec_id, 999),
        )

        parts: list[str] = []

        if low_confidence:
            parts.append(
                "> **Note:** This report was assembled with low-confidence evidence. "
                "Some claims may not be fully supported.\n"
            )

        for section in sorted_sections:
            if not section.content:
                log.debug("assemble_report: skipping empty section", spec_id=section.spec_id)
                continue
            parts.append(f"## {section.heading}\n")
            parts.append(section.content)
            if section.cited_source_ids:
                ids_str = ", ".join(section.cited_source_ids)
                parts.append(f"\n\n*Sources: {ids_str}*")
            parts.append("\n")

        report: str = "\n".join(parts).strip()

        log.info(
            "assemble_report: report assembled",
            sections=[s.spec_id for s in sorted_sections],
            char_count=len(report),
            low_confidence=low_confidence,
        )

        return {"report": report}

    except Exception as exc:
        msg = "assemble_report node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
