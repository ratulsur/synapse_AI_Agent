"""Drafted section model -- carries per-section source attribution.

Per ADR-005, grounding is graded and revised at section granularity, so each
Section must record exactly which sources it was written from / cited.

    class Section(BaseModel):
        spec_id: str            # FK to SectionSpec.id
        heading: str
        content: str            # drafted prose
        cited_source_ids: list[str]   # Source.id values this section relies on
        status: str             # 'pending' | 'drafted' | 'grounded' | 'revising'
        grounded: bool
        revise_count: int       # per-section revise loop counter

TODO(backend-developer): implement Section.

Owner: backend-developer
"""

# TODO(backend-developer): implement Section(BaseModel).
