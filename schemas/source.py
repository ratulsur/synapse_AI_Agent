"""The typed ``Source`` model -- the atomic unit of evidence.

Produced by tools.processing.normalize, deduped by tools.processing.dedup,
persisted by persistence.source_store, graded by the source grader, and cited
by the section writers.

Owner: backend-developer
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Source(BaseModel):
    """A single retrieved evidence unit.

    ``id`` is a stable content hash used for deduplication and cross-section
    citation.  It is computed automatically if not supplied.
    """

    id: str = Field(
        default="",
        description="Stable content hash for dedup and citation (auto-computed if empty).",
    )
    title: str = Field(description="Document / page title.")
    author: str | None = Field(default=None, description="Primary author(s).")
    url: str = Field(description="Canonical URL of the source.")
    domain: str = Field(
        description="Retrieval domain label (Techno / Education / Travel / Art / Mgmt / GENERIC)."
    )
    content: str = Field(
        default="",
        description="Extracted text / snippet used for grounding.",
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Relevance score from the retriever/grader (0..1).",
    )
    tool: str | None = Field(
        default=None,
        description="Which tool produced this source (web / wiki / arxiv / api / mcp).",
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of retrieval.",
    )

    @model_validator(mode="before")
    @classmethod
    def _compute_id(cls, values: Any) -> Any:
        """Auto-compute a content-hash id if one is not explicitly provided."""
        if isinstance(values, dict) and not values.get("id"):
            url = values.get("url", "")
            content = values.get("content", "")
            raw = f"{url}::{content[:512]}"
            values["id"] = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return values

    def model_post_init(self, __context: Any) -> None:
        """Ensure id is always non-empty."""
        if not self.id:
            raw = f"{self.url}::{self.content[:512]}"
            object.__setattr__(self, "id", hashlib.sha256(raw.encode()).hexdigest()[:16])
