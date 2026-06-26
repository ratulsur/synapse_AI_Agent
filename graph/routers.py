"""Conditional-edge routing functions for the StateGraph.

Each function inspects ``GraphState`` and returns the name of the next node (or
a list of node names for fan-out). Pure routing logic only — no side effects.

Routers to implement:
  * route_after_human(state) -> 'scope_plan' | 'query_router'
        Branch on state['plan_approved'] (approve vs revise).
  * route_query(state) -> list[str]
        Multi-label domain routing (Techno/Education/Travel/Art/Mgmt/GENERIC).
        Populates active_domains; GENERIC is the fallback when no label fires.
  * route_after_source_grader(state) -> 'tool_calls' | 'write'
        If grade fails AND retrieval_iteration < max -> back into the loop with
        a mutation_action; else proceed to write (set low_confidence if failing).
  * route_after_grounding_grader(state) -> 'revise_section' | 'assemble_report'
        Per-section: route to revise only the failing section(s); when all
        sections grounded OR revise_iteration >= max -> assemble_report.

TODO(backend-developer): implement the four routers above.

Owner: backend-developer
"""

# TODO(backend-developer): implement conditional-edge routers.
