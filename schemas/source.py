"""The typed ``Source`` model -- the atomic unit of evidence.

Produced by tools.processing.normalize, deduped by tools.processing.dedup,
persisted by persistence.source_store, graded by the source grader, and cited by
the section writers.

Intended fields:
    class Source(BaseModel):
        id: str                 # stable id (content hash) for dedup + citation
        title: str
        author: str | None
        url: str
        domain: str             # retrieval domain label (Techno/Travel/...)
        content: str            # extracted text / snippet used for grounding
        score: float            # relevance score from grader/retriever (0..1)
        tool: str | None        # which tool produced it (web/wiki/arxiv/api/mcp)
        retrieved_at: datetime

TODO(backend-developer): implement Source as a Pydantic model.

Owner: backend-developer
"""

# TODO(backend-developer): implement Source(BaseModel).
