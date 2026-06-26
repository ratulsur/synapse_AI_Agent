"""Node callables for the StateGraph.

Each module exposes a node function with the signature
``node(state: GraphState) -> dict`` (returning a partial state update). Nodes are
thin: they delegate reasoning to ``agents/`` and side-effecting work to
``tools/`` and ``persistence/``. Keep orchestration glue here, not business logic.

Owner: backend-developer (agent prompts injected by agent-prompt-engineer)
"""
