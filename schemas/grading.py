"""Shared output contract for the two LLM-judge graders.

Both the Source Grader (retrieval-evidence subgraph) and the Grounding Grader
(section-revise loop) return a ``GraderVerdict``.  Only the Source Grader
populates ``mutation_action``; only the Grounding Grader populates
``failing_section_ids``.

Owner: backend-developer (rubric semantics: agent-prompt-engineer)
"""

from enum import Enum

from pydantic import BaseModel, Field


class MutationAction(str, Enum):
    """Strategy the retrieval loop applies on a failing source grade.

    REFORMULATE  -- rewrite the query using the same domains/tools.
    WIDEN        -- relax filters / raise top_k, keep the same domains.
    REROUTE      -- add or swap domains+tools (e.g. fall back to GENERIC).
    """

    REFORMULATE = "reformulate"
    WIDEN = "widen"
    REROUTE = "reroute"


class GraderVerdict(BaseModel):
    """Structured verdict returned by both LLM-judge graders.

    Fields
    ------
    passed              YES/NO from the judge.
    score               Quality/grounding score in [0, 1].
    rationale           Free-text explanation (logged + surfaced in UI).
    mutation_action     Source Grader only: strategy for the next iteration.
    failing_section_ids Grounding Grader only: ids of sections that failed.
    """

    passed: bool = Field(description="Whether the grader's quality threshold was met.")
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Quality/grounding score (0..1).",
    )
    rationale: str = Field(
        default="",
        description="Human-readable explanation for the verdict.",
    )
    mutation_action: MutationAction | None = Field(
        default=None,
        description="Source Grader only: retrieval mutation strategy on failure.",
    )
    failing_section_ids: list[str] = Field(
        default_factory=list,
        description="Grounding Grader only: spec_ids of sections that need revision.",
    )
