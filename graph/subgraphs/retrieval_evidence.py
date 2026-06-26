"""Subgraph: Retrieval & Evidence Loop.

Internal topology (from research_agent_v2 diagram):
    tool_calls -> normalize -> deduplication -> save_checkpoint -> source_grader
    source_grader --pass--> (exit to parent: write)
    source_grader --fail--> iteration_gate
    iteration_gate --iteration < max--> tool_calls   (apply mutation_action)
    iteration_gate --iteration >= max--> (exit, set low_confidence)

Nodes:
  * tool_calls       -> agents.react_agent + tools.registry (ReAct over the
                        active domains; web / wiki / wikivoyage / arXiv / API / MCP).
  * normalize        -> tools.processing.normalize (raw hits -> Source).
  * deduplication    -> tools.processing.dedup (url/content-hash match).
  * save_checkpoint  -> persistence.source_store + checkpointer (typed Source[]).
  * source_grader    -> agents.graders.source_grader (LLM judge -> GraderVerdict).
  * iteration_gate   -> increments retrieval_iteration; the branch decision lives
                        in graph.routers.route_after_source_grader.

Mutation strategy on a failing grade (see ADR-006): the grader returns one of
'reformulate' (rewrite query, same domains/tools), 'widen' (relax filters /
raise top_k, same domains), or 'reroute' (add/swap domains+tools, e.g. fall back
to GENERIC). The NO edge therefore MAY re-route to different domains/tools, not
only re-retrieve on the same path.

TODO(backend-developer): implement build_retrieval_subgraph().

Owner: backend-developer (grader rubric: agent-prompt-engineer)
"""

# TODO(backend-developer): implement build_retrieval_subgraph().
