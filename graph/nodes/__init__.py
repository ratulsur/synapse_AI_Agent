"""Node callables for the StateGraph.

Each module exposes a node function with the signature
``node(state: GraphState) -> dict`` (returning a partial state update).  Nodes
are thin: they delegate reasoning to ``agents/`` and side-effecting work to
``tools/`` and ``persistence/``.  Keep orchestration glue here, not business
logic.

Owner: backend-developer (agent prompts injected by agent-prompt-engineer)
"""

from graph.nodes.assemble_report import assemble_report
from graph.nodes.create_analyst import create_analyst
from graph.nodes.final_answer import final_answer
from graph.nodes.grounding_grader import grounding_grader
from graph.nodes.human_in_the_loop import human_in_the_loop
from graph.nodes.query_router import query_router
from graph.nodes.revise_section import revise_section
from graph.nodes.scope_plan import scope_plan
from graph.nodes.write import write

__all__ = [
    "assemble_report",
    "create_analyst",
    "final_answer",
    "grounding_grader",
    "human_in_the_loop",
    "query_router",
    "revise_section",
    "scope_plan",
    "write",
]
