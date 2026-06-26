"""Report plan + section specification models.

    class SectionSpec(BaseModel):
        id: str                 # e.g. 'intro' | 'body' | 'conclusion' | custom
        heading: str
        intent: str             # what this section must cover
        order: int

    class ReportPlan(BaseModel):
        audience: str
        length: str             # e.g. 'short' | 'medium' | 'long' or word target
        tone: str
        sections: list[SectionSpec]

TODO(backend-developer): implement ReportPlan and SectionSpec.

Owner: backend-developer
"""

# TODO(backend-developer): implement ReportPlan, SectionSpec.
