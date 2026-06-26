"""Node: Write (plan sections scaffold).

Transition node between the retrieval-evidence subgraph and the
section-drafting subgraph.  Expands the approved plan into per-section
``Section`` stubs (status='pending') that the parallel section writers will
populate.

This is a purely deterministic node -- no LLM call.

Owner: Ratul Sur
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.plan import ReportPlan
from schemas.section import Section


def write(state: GraphState) -> dict:
    """Create a Section stub for every SectionSpec in the plan.

    Existing sections that already have content (from a previous run or a
    revise cycle) are preserved -- only pending stubs are (re)created for
    sections not yet present in state.

    Returns a partial state update with key:
        sections  -- list[Section]  (all stubs, merged via merge_sections_reducer)
    """
    try:
        plan: ReportPlan | None = state.get("plan")
        if plan is None:
            log.warning("write: no plan in state, returning empty sections")
            return {"sections": []}

        existing_sections: list[Section] = state.get("sections") or []
        existing_ids: set[str] = {s.spec_id for s in existing_sections}

        new_stubs: list[Section] = []
        for spec in plan.sorted_sections():
            if spec.id not in existing_ids:
                new_stubs.append(
                    Section(
                        spec_id=spec.id,
                        heading=spec.heading,
                        content="",
                        cited_source_ids=[],
                        status="pending",
                        grounded=False,
                        revise_count=0,
                    )
                )

        log.info(
            "write: section stubs created",
            new_stubs=[s.spec_id for s in new_stubs],
            already_present=list(existing_ids),
        )

        return {"sections": new_stubs}

    except Exception as exc:
        msg = "write node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
