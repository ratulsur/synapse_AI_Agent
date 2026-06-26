"""Subgraph: Parallel Section Drafting.

Fans out to three concurrent writer agents, then fans back in:

    START -> write_intro  --|
          -> write_body   --|-> join_sections -> END
          -> write_conclusion --|

Each writer consumes the plan SectionSpec for its role plus the full source
list, produces a ``Section`` with ``status='drafted'`` and
``cited_source_ids`` populated, and emits it via ``sections``.

``merge_sections_reducer`` in ``GraphState`` handles concurrent updates from
the three parallel writers without collisions (keyed by spec_id).

Writer sections are identified by the ``SectionSpec.id`` field:
    'intro'       -> write_intro
    'body'        -> write_body
    'conclusion'  -> write_conclusion

If the plan uses non-standard spec_ids, each writer falls back to picking the
section by its order (first, middle, last).

Stub behaviour: when the writer agents are not yet implemented, the nodes fill
in placeholder prose so the graph can reach assemble_report end-to-end.

Owner: backend-developer (writer prompts: agent-prompt-engineer)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.plan import ReportPlan, SectionSpec
from schemas.section import Section
from schemas.source import Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_spec(plan: ReportPlan | None, role_id: str, order_fallback: int) -> SectionSpec | None:
    """Locate a SectionSpec by id first, then by order position."""
    if plan is None:
        return None
    # Exact id match
    for spec in plan.sections:
        if spec.id == role_id:
            return spec
    # Fallback: take the spec at the given ordinal position (0-based)
    sorted_specs = plan.sorted_sections()
    if 0 <= order_fallback < len(sorted_specs):
        return sorted_specs[order_fallback]
    return None


def _stub_section(spec: SectionSpec, role: str, sources: list[Source]) -> Section:
    """Return a placeholder drafted section when the writer agent is not ready."""
    source_ids = [s.id for s in sources[:3]]  # cite first three sources as stub
    return Section(
        spec_id=spec.id,
        heading=spec.heading,
        content=(
            f"[Stub draft for '{spec.heading}'. "
            f"Writer agent '{role}' not yet implemented. "
            f"Intent: {spec.intent or 'N/A'}]"
        ),
        cited_source_ids=source_ids,
        status="drafted",
        grounded=False,
        revise_count=0,
    )


# ---------------------------------------------------------------------------
# Writer node callables
# ---------------------------------------------------------------------------

def _write_intro(state: GraphState) -> dict:
    """Write the introduction section."""
    try:
        plan: ReportPlan | None = state.get("plan")
        sources: list[Source] = state.get("sources") or []
        spec = _find_spec(plan, "intro", order_fallback=0)

        if spec is None:
            log.debug("section_drafting/write_intro: no intro spec found, skipping")
            return {}

        log.info("section_drafting/write_intro: drafting intro", heading=spec.heading)

        try:
            from agents.writers import write_intro  # type: ignore[import]
            section: Section = write_intro(state, spec)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("section_drafting/write_intro: writer stub not ready")
            section = _stub_section(spec, "write_intro", sources)

        return {"sections": [section]}

    except Exception as exc:
        msg = "section_drafting write_intro node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _write_body(state: GraphState) -> dict:
    """Write the body / main analysis section."""
    try:
        plan: ReportPlan | None = state.get("plan")
        sources: list[Source] = state.get("sources") or []
        spec = _find_spec(plan, "body", order_fallback=1)

        if spec is None:
            log.debug("section_drafting/write_body: no body spec found, skipping")
            return {}

        log.info("section_drafting/write_body: drafting body", heading=spec.heading)

        try:
            from agents.writers import write_body  # type: ignore[import]
            section: Section = write_body(state, spec)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("section_drafting/write_body: writer stub not ready")
            section = _stub_section(spec, "write_body", sources)

        return {"sections": [section]}

    except Exception as exc:
        msg = "section_drafting write_body node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _write_conclusion(state: GraphState) -> dict:
    """Write the conclusion section."""
    try:
        plan: ReportPlan | None = state.get("plan")
        sources: list[Source] = state.get("sources") or []
        spec = _find_spec(plan, "conclusion", order_fallback=2)

        if spec is None:
            log.debug("section_drafting/write_conclusion: no conclusion spec found, skipping")
            return {}

        log.info("section_drafting/write_conclusion: drafting conclusion", heading=spec.heading)

        try:
            from agents.writers import write_conclusion  # type: ignore[import]
            section: Section = write_conclusion(state, spec)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("section_drafting/write_conclusion: writer stub not ready")
            section = _stub_section(spec, "write_conclusion", sources)

        return {"sections": [section]}

    except Exception as exc:
        msg = "section_drafting write_conclusion node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _join_sections(state: GraphState) -> dict:
    """No-op synchronisation barrier; waits for all parallel writers to finish."""
    log.debug(
        "section_drafting/join_sections: all writers complete",
        section_count=len(state.get("sections") or []),
    )
    return {}


# ---------------------------------------------------------------------------
# Subgraph factory
# ---------------------------------------------------------------------------

def build_section_drafting_subgraph() -> object:
    """Build and compile the parallel section-drafting subgraph.

    Topology::

        START -> write_intro  --|
              -> write_body   --|-> join_sections -> END
              -> write_conclusion --|

    Returns
    -------
    CompiledStateGraph
        A compiled LangGraph subgraph ready to be embedded as a node in the
        parent graph via ``parent.add_node("section_drafting", subgraph)``.
    """
    try:
        builder = StateGraph(GraphState)

        builder.add_node("write_intro", _write_intro)
        builder.add_node("write_body", _write_body)
        builder.add_node("write_conclusion", _write_conclusion)
        builder.add_node("join_sections", _join_sections)

        # Fan-out: START branches to all three writers in parallel.
        builder.add_edge(START, "write_intro")
        builder.add_edge(START, "write_body")
        builder.add_edge(START, "write_conclusion")

        # Fan-in: all three converge at join_sections.
        builder.add_edge("write_intro", "join_sections")
        builder.add_edge("write_body", "join_sections")
        builder.add_edge("write_conclusion", "join_sections")

        builder.add_edge("join_sections", END)

        compiled = builder.compile()
        log.info("section_drafting subgraph compiled successfully")
        return compiled

    except Exception as exc:
        msg = "Failed to build section_drafting subgraph"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
