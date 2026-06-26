"""Node: Human-in-the-loop (approve / edit plan).

Uses ``langgraph.types.interrupt`` to pause execution and surface the current
``ReportPlan`` to a human reviewer.  The graph checkpointer persists state
across the pause.

Resume contract (consumed by ``api/`` and ``frontend/``):
    The caller resumes the graph by passing a ``Command`` with a resume value
    of shape::

        {"approved": True}
            or
        {"approved": False, "plan": <serialised ReportPlan dict>}

    On approve  -> sets ``plan_approved = True`` -> router sends to query_router.
    On revise   -> writes edited plan back into state, ``plan_approved = False``
                -> router sends back to scope_plan.

Owner: Ratul Sur
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.plan import ReportPlan


def human_in_the_loop(state: GraphState) -> dict:
    """Interrupt and wait for a human to approve or edit the plan.

    Returns a partial state update with keys:
        plan_approved  -- bool
        plan           -- ReportPlan (unchanged on approve, edited on revise)
    """
    # NOTE: langgraph.types.interrupt() raises GraphInterrupt internally.
    # That signal must NOT be caught -- let it propagate so LangGraph can
    # persist the checkpoint and surface the interrupt event to the caller.
    from langgraph.errors import GraphInterrupt  # noqa: F401 (imported for clarity)
    from langgraph.types import interrupt  # local import to keep testable without LG

    plan: ReportPlan | None = state.get("plan")
    query: str = state.get("query", "")

    log.info("human_in_the_loop: pausing for human review", query_preview=query[:80])

    # Surface the plan payload; the frontend/API layer reads this from the
    # interrupt event stream.
    human_input: dict = interrupt(
        {
            "event": "plan_review",
            "query": query,
            "plan": plan.model_dump() if plan else None,
            "instructions": (
                "Review the report plan.  "
                "Respond with {'approved': True} to proceed, or "
                "{'approved': False, 'plan': <edited_plan_dict>} to revise."
            ),
        }
    )

    # Execution resumes here after the caller provides a Command with a resume value.
    try:
        approved: bool = human_input.get("approved", False)

        if approved:
            log.info("human_in_the_loop: plan approved")
            return {"plan_approved": True}

        # Human provided edits -- parse the plan update.
        edited_plan_data: dict | None = human_input.get("plan")
        if edited_plan_data and isinstance(edited_plan_data, dict):
            try:
                edited_plan = ReportPlan.model_validate(edited_plan_data)
            except Exception as parse_exc:
                log.warning(
                    "human_in_the_loop: could not parse edited plan, keeping original",
                    error=str(parse_exc),
                )
                edited_plan = plan  # fall back to current plan
        else:
            edited_plan = plan  # no edits provided

        log.info("human_in_the_loop: plan sent for revision")
        return {"plan": edited_plan, "plan_approved": False}

    except Exception as exc:
        msg = "human_in_the_loop node failed after resume"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
