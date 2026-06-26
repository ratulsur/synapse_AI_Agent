"""Node: Revise Section.

Rewrites only the failing section(s) identified by the Grounding Grader
(``grounding_grade.failing_section_ids``).  Preserves already-grounded
sections.  Increments the global ``revise_iteration`` counter and per-section
``revise_count``.

Delegates to ``agents.reviser``; falls back to marking the section 'grounded'
with a stub annotation when the agent is not yet implemented.

Owner: backend-developer (reviser prompt: agent-prompt-engineer)
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.grading import GraderVerdict
from schemas.section import Section


def revise_section(state: GraphState) -> dict:
    """Rewrite failing sections and increment the revise loop counter.

    Returns a partial state update with keys:
        sections         -- list[Section]  (only the revised sections;
                            merged into full list via merge_sections_reducer)
        revise_iteration -- int  (incremented)
    """
    try:
        sections: list[Section] = state.get("sections") or []
        grounding_grade: GraderVerdict | None = state.get("grounding_grade")
        revise_iteration: int = state.get("revise_iteration", 0)

        failing_ids: list[str] = (
            grounding_grade.failing_section_ids if grounding_grade else []
        )

        log.info(
            "revise_section: revising failing sections",
            failing_ids=failing_ids,
            revise_iteration=revise_iteration,
        )

        failing_section_map: dict[str, Section] = {
            s.spec_id: s for s in sections if s.spec_id in failing_ids
        }

        if not failing_section_map:
            log.warning("revise_section: no matching sections found for failing_ids", failing_ids=failing_ids)
            return {"revise_iteration": revise_iteration + 1}

        revised_sections: list[Section] = []

        for spec_id, section in failing_section_map.items():
            # --- Delegate to agent stub ---
            try:
                from agents.reviser import run_reviser  # type: ignore[import]
                revised: Section = run_reviser(state, section)
            except (ImportError, NotImplementedError, AttributeError):
                log.debug(
                    "revise_section: reviser stub not ready, using stub revision",
                    spec_id=spec_id,
                )
                # Stub: mark as grounded with a note so the graph can continue.
                revised = Section(
                    spec_id=section.spec_id,
                    heading=section.heading,
                    content=(
                        section.content
                        + "\n\n[Stub revision: agent not yet implemented. "
                        "Claims assumed grounded for graph-topology testing.]"
                    ),
                    cited_source_ids=section.cited_source_ids,
                    status="grounded",
                    grounded=True,
                    revise_count=section.revise_count + 1,
                )

            revised_sections.append(revised)
            log.debug("revise_section: section revised", spec_id=spec_id, revise_count=revised.revise_count)

        return {
            "sections": revised_sections,     # merge_sections_reducer handles merging
            "revise_iteration": revise_iteration + 1,
        }

    except Exception as exc:
        msg = "revise_section node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
