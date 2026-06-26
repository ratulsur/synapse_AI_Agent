"""Graph assembly: build, wire, and compile the StateGraph.

``build_graph()`` is the single entry point.  It:
    1. Instantiates ``StateGraph(GraphState)``.
    2. Registers every parent-graph node from ``graph.nodes`` and the two
       compiled subgraphs from ``graph.subgraphs``.
    3. Wires static edges.
    4. Wires conditional edges using the four routers from ``graph.routers``.
    5. Attaches a ``MemorySaver`` checkpointer (the dedicated SQLite-backed
       checkpointer from ``persistence.checkpointer`` is wired here when that
       module is ready).
    6. Configures ``human_in_the_loop`` as an interrupt point (the interrupt
       call lives inside the node itself via ``langgraph.types.interrupt``).

Edge map (matches ARCHITECTURE.md and research_agent_v2.jpg):
    START -> create_analyst -> scope_plan -> human_in_the_loop
    human_in_the_loop --approve--> query_router
    human_in_the_loop --revise--> scope_plan
    query_router -> retrieval_evidence (subgraph)
    retrieval_evidence -> write
    write -> section_drafting (subgraph)
    section_drafting -> grounding_grader
    grounding_grader --ungrounded--> revise_section -> grounding_grader
    grounding_grader --grounded--> assemble_report -> final_answer -> END

Owner: backend-developer
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from exception.custom_exception import ResearchAnalystException
from graph.nodes import (
    assemble_report,
    create_analyst,
    final_answer,
    grounding_grader,
    human_in_the_loop,
    query_router,
    revise_section,
    scope_plan,
    write,
)
from graph.routers import (
    route_after_grounding_grader,
    route_after_human,
)
from graph.state import GraphState
from graph.subgraphs.retrieval_evidence import build_retrieval_subgraph
from graph.subgraphs.section_drafting import build_section_drafting_subgraph
from log import GLOBAL_LOGGER as log


def _get_checkpointer() -> MemorySaver:
    """Return a checkpointer instance.

    When ``persistence.checkpointer`` is wired (SQLite-backed), swap this call
    for ``from persistence.checkpointer import get_checkpointer; return
    get_checkpointer()``.  Until then, ``MemorySaver`` provides correct
    interrupt / resume semantics in-process.
    """
    try:
        from persistence.checkpointer import get_checkpointer  # type: ignore[import]
        return get_checkpointer()
    except (ImportError, NotImplementedError, AttributeError):
        log.debug("builder: persistence.checkpointer stub not ready, using MemorySaver")
        return MemorySaver()


def build_graph():
    """Assemble, wire, and compile the full research-report StateGraph.

    Returns
    -------
    CompiledStateGraph
        Ready to run via ``graph.invoke(initial_state, config)``.

    Usage example::

        from graph.builder import build_graph
        g = build_graph()
        config = {"configurable": {"thread_id": "run-001"}}
        result = g.invoke({"query": "What is quantum computing?"}, config)
    """
    try:
        log.info("builder: assembling research-report graph")

        # --- Build subgraphs ---
        retrieval_subgraph = build_retrieval_subgraph()
        section_drafting_subgraph = build_section_drafting_subgraph()

        # --- Parent graph ---
        builder = StateGraph(GraphState)

        # Register parent-graph nodes
        builder.add_node("create_analyst", create_analyst)
        builder.add_node("scope_plan", scope_plan)
        builder.add_node("human_in_the_loop", human_in_the_loop)
        builder.add_node("query_router", query_router)
        builder.add_node("retrieval_evidence", retrieval_subgraph)
        builder.add_node("write", write)
        builder.add_node("section_drafting", section_drafting_subgraph)
        builder.add_node("grounding_grader", grounding_grader)
        builder.add_node("revise_section", revise_section)
        builder.add_node("assemble_report", assemble_report)
        builder.add_node("final_answer", final_answer)

        # --- Static edges ---
        builder.add_edge(START, "create_analyst")
        builder.add_edge("create_analyst", "scope_plan")
        builder.add_edge("scope_plan", "human_in_the_loop")
        # query_router -> retrieval_evidence (static; domain selection is state, not fork)
        builder.add_edge("query_router", "retrieval_evidence")
        # retrieval_evidence subgraph exits to write
        builder.add_edge("retrieval_evidence", "write")
        builder.add_edge("write", "section_drafting")
        builder.add_edge("section_drafting", "grounding_grader")
        # revise loop: revise_section always returns to grounding_grader
        builder.add_edge("revise_section", "grounding_grader")
        builder.add_edge("assemble_report", "final_answer")
        builder.add_edge("final_answer", END)

        # --- Conditional edges ---
        # 1. After human_in_the_loop: approve -> query_router, revise -> scope_plan
        builder.add_conditional_edges(
            "human_in_the_loop",
            route_after_human,
            {
                "query_router": "query_router",
                "scope_plan": "scope_plan",
            },
        )

        # 2. After grounding_grader: ungrounded -> revise_section, all clear -> assemble_report
        builder.add_conditional_edges(
            "grounding_grader",
            route_after_grounding_grader,
            {
                "revise_section": "revise_section",
                "assemble_report": "assemble_report",
            },
        )

        # --- Checkpointer + interrupt ---
        checkpointer = _get_checkpointer()

        # The human_in_the_loop node uses langgraph.types.interrupt() internally,
        # which requires a checkpointer.  No interrupt_before config needed when
        # using the in-node interrupt() API.
        compiled = builder.compile(checkpointer=checkpointer)

        log.info("builder: graph compiled successfully", type=type(compiled).__name__)
        return compiled

    except Exception as exc:
        msg = "build_graph failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
