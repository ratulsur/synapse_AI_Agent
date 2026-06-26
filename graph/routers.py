"""Conditional-edge routing functions for the StateGraph.

Each function inspects ``GraphState`` and returns the name of the next node (or
the ``END`` sentinel to exit a subgraph).  Pure routing logic only -- no side
effects, no LLM calls.

Routers
-------
route_after_human         Branch on ``plan_approved``: approve -> query_router,
                          revise -> scope_plan.
route_query               After query_router node: always routes to
                          retrieval_evidence (active_domains already set in state
                          by the query_router node).
route_after_source_grader Inside the retrieval-evidence subgraph: pass -> exit
                          (END); fail & under cap -> tool_calls (with
                          mutation_action); fail & at cap -> exit + low_confidence.
route_after_grounding_grader  Per-section: failing_section_ids & under cap ->
                              revise_section; all grounded or at cap ->
                              assemble_report.

Owner: Ratul Sur
"""

from __future__ import annotations

from langgraph.graph import END

from graph.state import GraphState
from log import GLOBAL_LOGGER as log


# ---------------------------------------------------------------------------
# 1. route_after_human
# ---------------------------------------------------------------------------

def route_after_human(state: GraphState) -> str:
    """Branch after the Human-in-the-loop node.

    Returns 'query_router' when the plan is approved, 'scope_plan' when the
    human requests a revision.
    """
    plan_approved: bool = state.get("plan_approved", False)

    if plan_approved:
        log.debug("route_after_human: plan approved -> query_router")
        return "query_router"
    else:
        log.debug("route_after_human: plan not approved -> scope_plan (revise)")
        return "scope_plan"


# ---------------------------------------------------------------------------
# 2. route_query
# ---------------------------------------------------------------------------

def route_query(state: GraphState) -> str:
    """Route after the query_router node.

    The query_router node has already populated ``active_domains`` in state.
    This router unconditionally sends execution to the retrieval_evidence
    subgraph; domain selection was a state update, not a graph fork.
    """
    active_domains: list[str] = state.get("active_domains", [])
    log.debug("route_query -> retrieval_evidence", active_domains=active_domains)
    return "retrieval_evidence"


# ---------------------------------------------------------------------------
# 3. route_after_source_grader  (used inside retrieval_evidence subgraph)
# ---------------------------------------------------------------------------

def route_after_source_grader(state: GraphState) -> str:
    """Branch after the source_grader node inside the retrieval-evidence loop.

    Decision table:
    - grade.passed                             -> END (exit subgraph to write)
    - not passed AND iteration < max           -> "tool_calls" (apply mutation)
    - not passed AND iteration >= max          -> END (low_confidence already set)
    """
    from schemas.grading import GraderVerdict  # local import to avoid circulars

    source_grade: GraderVerdict | None = state.get("source_grade")
    retrieval_iteration: int = state.get("retrieval_iteration", 0)
    max_retrieval_iterations: int = state.get("max_retrieval_iterations", 3)

    if source_grade is not None and source_grade.passed:
        log.debug(
            "route_after_source_grader: passed -> exit subgraph",
            score=source_grade.score,
            iteration=retrieval_iteration,
        )
        return END

    # Grade not passed (or no grade yet)
    if retrieval_iteration < max_retrieval_iterations:
        action = state.get("mutation_action", "reformulate")
        log.debug(
            "route_after_source_grader: fail -> tool_calls",
            iteration=retrieval_iteration,
            max=max_retrieval_iterations,
            mutation_action=action,
        )
        return "tool_calls"
    else:
        log.debug(
            "route_after_source_grader: at cap -> exit subgraph (low_confidence)",
            iteration=retrieval_iteration,
            max=max_retrieval_iterations,
        )
        return END


# ---------------------------------------------------------------------------
# 4. route_after_grounding_grader
# ---------------------------------------------------------------------------

def route_after_grounding_grader(state: GraphState) -> str:
    """Branch after the grounding_grader node in the parent graph.

    Decision table:
    - failing_section_ids non-empty AND revise_iteration < max -> "revise_section"
    - all sections grounded OR at cap                          -> "assemble_report"
    """
    from schemas.grading import GraderVerdict  # local import

    grounding_grade: GraderVerdict | None = state.get("grounding_grade")
    revise_iteration: int = state.get("revise_iteration", 0)
    max_revise_iterations: int = state.get("max_revise_iterations", 2)

    if grounding_grade is None:
        log.debug("route_after_grounding_grader: no grade yet -> assemble_report")
        return "assemble_report"

    failing_ids: list[str] = grounding_grade.failing_section_ids or []

    if failing_ids and revise_iteration < max_revise_iterations:
        log.debug(
            "route_after_grounding_grader: ungrounded sections -> revise_section",
            failing=failing_ids,
            iteration=revise_iteration,
            max=max_revise_iterations,
        )
        return "revise_section"
    else:
        if failing_ids:
            log.debug(
                "route_after_grounding_grader: at revise cap -> assemble_report",
                iteration=revise_iteration,
                max=max_revise_iterations,
            )
        else:
            log.debug("route_after_grounding_grader: all grounded -> assemble_report")
        return "assemble_report"
