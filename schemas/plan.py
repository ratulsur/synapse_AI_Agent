"""Report plan + section specification models.

Produced by the Scope & Plan agent, approved / edited by the Human-in-the-loop
node, and consumed by the Write node (to scaffold sections) and the section
writer agents.

Owner: backend-developer
"""

from pydantic import BaseModel, Field


class SectionSpec(BaseModel):
    """Specification for one section of the report.

    Fields
    ------
    id       Stable identifier used for routing and cross-referencing
             (e.g. 'intro', 'body', 'conclusion', or a custom slug).
    heading  Display heading rendered in the final report.
    intent   What this section must cover (used as writer agent instruction).
    order    Ordinal position in the assembled report (ascending).
    """

    id: str = Field(description="Stable section identifier (e.g. 'intro', 'body', 'conclusion').")
    heading: str = Field(description="Display heading for the section.")
    intent: str = Field(
        default="",
        description="High-level instruction for what this section must cover.",
    )
    order: int = Field(
        default=0,
        description="Ordinal position in the assembled report (ascending, 0-based).",
    )


class ReportPlan(BaseModel):
    """Audience, tone, length, and ordered section specifications.

    Produced by the Scope & Plan agent; modified on revise cycles.
    """

    audience: str = Field(
        default="general",
        description="Intended audience for the report (e.g. 'general public', 'executives').",
    )
    length: str = Field(
        default="medium",
        description="Approximate length: 'short' | 'medium' | 'long' or a word target.",
    )
    tone: str = Field(
        default="neutral",
        description="Writing tone: e.g. 'formal', 'conversational', 'neutral'.",
    )
    sections: list[SectionSpec] = Field(
        default_factory=list,
        description="Ordered section specifications (sorted by SectionSpec.order).",
    )

    def sorted_sections(self) -> list[SectionSpec]:
        """Return sections sorted by their order field."""
        return sorted(self.sections, key=lambda s: s.order)
