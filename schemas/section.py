"""Drafted section model -- carries per-section source attribution.

Per the architecture, grounding is graded and revised at section granularity
(not whole-draft), so each Section records exactly which sources it was written
from / cited (``cited_source_ids``).

Owner: Ratul Sur
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SectionStatus = Literal["pending", "drafted", "grounded", "revising"]


class Section(BaseModel):
    """One drafted (or pending) section of the report.

    Fields
    ------
    spec_id           FK to ``SectionSpec.id``.
    heading           Display heading (copied from SectionSpec.heading).
    content           Drafted prose; empty string when status='pending'.
    cited_source_ids  ``Source.id`` values this section relies on.
    status            Lifecycle state of the section.
    grounded          Whether the Grounding Grader has cleared this section.
    revise_count      Number of times this section has been through Revise Section.
    """

    spec_id: str = Field(description="FK to SectionSpec.id.")
    heading: str = Field(description="Display heading for this section.")
    content: str = Field(
        default="",
        description="Drafted prose; empty when status='pending'.",
    )
    cited_source_ids: list[str] = Field(
        default_factory=list,
        description="Source.id values this section cites.",
    )
    status: SectionStatus = Field(
        default="pending",
        description="Lifecycle: pending | drafted | grounded | revising.",
    )
    grounded: bool = Field(
        default=False,
        description="True when the Grounding Grader has cleared this section.",
    )
    revise_count: int = Field(
        default=0,
        description="Number of revise-section cycles applied.",
    )
