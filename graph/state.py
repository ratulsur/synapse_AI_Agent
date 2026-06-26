"""Top-level LangGraph state schema for the research-report agent.

This is the single typed object that flows through every node and subgraph.
LangGraph merges partial dict updates returned by nodes into this state; list
fields that accumulate across nodes (e.g. ``sources``, ``messages``) should be
annotated with reducer functions (``operator.add`` / custom reducers).

Sketch of the intended ``GraphState`` (do NOT implement logic here — fields and
reducers only):

    class GraphState(TypedDict):
        # --- inputs / framing ---
        query: str                       # original user research question
        analyst: AnalystPersona          # role/persona from Create Analyst node
        plan: ReportPlan                 # audience, length, tone, section specs
        plan_approved: bool              # set True by Human-in-the-loop approve

        # --- routing ---
        route_labels: list[str]          # multi-label output of Query Router
        active_domains: list[str]        # subset of DOMAINS to retrieve against

        # --- retrieval / evidence loop ---
        sources: Annotated[list[Source], add_sources]   # accumulated, deduped
        retrieval_iteration: int         # current loop count
        max_retrieval_iterations: int    # iteration cap
        source_grade: GraderVerdict       # last Source Grader judgement
        mutation_action: str | None      # 'reformulate' | 'widen' | 'reroute'
        low_confidence: bool             # set when loop exits without passing grade

        # --- drafting ---
        sections: Annotated[list[Section], merge_sections]  # intro/body/conclusion
        grounding_grade: GraderVerdict    # last Grounding Grader judgement
        revise_iteration: int             # grounding revise loop count
        max_revise_iterations: int        # cap for grounding loop

        # --- output ---
        report: str                       # assembled report
        final_answer: str                 # terminal payload returned to caller

        # --- bookkeeping ---
        messages: Annotated[list, add_messages]  # ReAct / agent scratch
        errors: list[str]

TODO(backend-developer): finalize TypedDict/Pydantic choice, add reducer
annotations, and re-export the concrete types from ``schemas``.

Owner: backend-developer (schema contracts co-owned with schemas/)
"""

# TODO(backend-developer): implement GraphState and reducer helpers.
