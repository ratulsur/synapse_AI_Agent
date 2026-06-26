"""Node: Scope & Plan.

Produces the ``ReportPlan`` (audience, length, tone, ordered section specs)
from the query and analyst persona.  This node is re-entered on a human
revise cycle (Human-in-the-loop -> scope_plan -> human_in_the_loop).

Delegates to ``agents.planner``; falls back to a three-section default plan if
the planner stub is not yet implemented.

Owner: backend-developer (planning prompt: agent-prompt-engineer)
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.plan import ReportPlan, SectionSpec


def scope_plan(state: GraphState) -> dict:
    """Produce or revise the ReportPlan.

    Returns a partial state update with key:
        plan  -- ReportPlan
    """
    try:
        query: str = state.get("query", "")
        analyst = state.get("analyst")
        log.info("scope_plan: generating report plan", query_preview=query[:80])

        # --- Delegate to agent stub ---
        try:
            from agents.planner import run_planner  # type: ignore[import]
            plan: ReportPlan = run_planner(state)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("scope_plan: planner stub not ready, using default plan")
            plan = _default_plan(query)

        log.info(
            "scope_plan: plan produced",
            audience=plan.audience,
            sections=[s.id for s in plan.sections],
        )
        return {"plan": plan}

    except Exception as exc:
        msg = "scope_plan node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _default_plan(query: str) -> ReportPlan:
    """Return a minimal three-section plan when the planner agent is not ready."""
    return ReportPlan(
        audience="general",
        length="medium",
        tone="neutral",
        sections=[
            SectionSpec(
                id="intro",
                heading="Introduction",
                intent=f"Provide background and context for: {query}",
                order=0,
            ),
            SectionSpec(
                id="body",
                heading="Main Analysis",
                intent=f"Present key findings and analysis for: {query}",
                order=1,
            ),
            SectionSpec(
                id="conclusion",
                heading="Conclusion",
                intent="Summarise findings and suggest next steps.",
                order=2,
            ),
        ],
    )
