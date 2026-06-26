"""Graph assembly: build, wire, and compile the StateGraph.

Responsibilities:
  * Instantiate ``StateGraph(GraphState)``.
  * Register every node from ``graph.nodes`` and both subgraphs from
    ``graph.subgraphs``.
  * Wire static edges and conditional edges (see ``graph.routers``).
  * Attach the SQLite checkpointer from ``persistence.checkpointer``.
  * Configure interrupt points for the Human-in-the-loop node.
  * Expose a ``build_graph()`` factory returning a compiled graph.

Edge map (from research_agent_v2 diagram):
  START -> create_analyst -> scope_plan -> human_in_the_loop
  human_in_the_loop --approve--> query_router
  human_in_the_loop --revise--> scope_plan
  query_router -> retrieval_evidence (subgraph)
  retrieval_evidence -> write
  write -> section_drafting (subgraph)
  section_drafting -> grounding_grader
  grounding_grader --ungrounded--> revise_section --> grounding_grader
  grounding_grader --grounded--> assemble_report -> final_answer -> END

TODO(backend-developer): implement build_graph().

Owner: backend-developer
"""

# TODO(backend-developer): implement build_graph() and compile with checkpointer.
