"""Shared output contract for the two LLM-judge graders.

    class MutationAction(str, Enum):
        REFORMULATE = 'reformulate'   # rewrite query, same domains/tools
        WIDEN = 'widen'               # relax filters / raise top_k, same domains
        REROUTE = 'reroute'           # add/swap domains+tools (e.g. -> GENERIC)

    class GraderVerdict(BaseModel):
        passed: bool                  # YES/NO from the judge
        score: float                  # 0..1 quality/grounding score
        rationale: str                # why (for logs + frontend transparency)
        # Source Grader only:
        mutation_action: MutationAction | None
        # Grounding Grader only:
        failing_section_ids: list[str]    # sections to send to Revise Section

TODO(backend-developer): implement GraderVerdict + MutationAction.

Owner: backend-developer (rubric semantics: agent-prompt-engineer)
"""

# TODO(backend-developer): implement GraderVerdict, MutationAction.
