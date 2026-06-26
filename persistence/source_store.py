"""Typed Source[] store backed by SQLite (the "Save + Checkpoint" node).

Persists deduped schemas.source.Source rows keyed by run thread_id + Source.id,
separate from the graph checkpoint blob so sources are queryable/auditable.

Intended API:
    def save_sources(thread_id: str, sources: list[Source]) -> None: ...
    def load_sources(thread_id: str) -> list[Source]: ...

Owner: backend-developer
"""

# TODO(backend-developer): implement Source store.
