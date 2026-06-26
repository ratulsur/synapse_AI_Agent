"""API application factory (FastAPI suggested).

Builds the app, loads the compiled graph from graph.builder, and mounts routes.
Intended endpoints:
    POST /runs                -> start a run (query) -> {thread_id, state}
    GET  /runs/{id}/stream    -> stream node events (SSE) for the UI timeline
    POST /runs/{id}/resume    -> resume after human-in-the-loop (approve/revise)
    GET  /runs/{id}           -> fetch current state / final answer + sources

Owner: backend-developer
"""

# TODO(backend-developer): implement create_app().
