"""Node: Human-in-the-loop (approve / edit plan).

Uses a LangGraph ``interrupt`` to pause execution and surface the plan to a human
for approval or edit. On resume, sets ``plan_approved`` (approve -> query_router)
or writes edits back into ``plan`` and routes to scope_plan (revise). The
interrupt/resume contract is consumed by the api/ + frontend/ layers.

Owner: backend-developer (interrupt UX: frontend-ui-developer)
"""

# TODO(backend-developer): def human_in_the_loop(state) -> dict  (with interrupt)
