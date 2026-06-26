"""Deduplicate Source[] by url and content hash.

Merges duplicates across tools/iterations, keeping the highest-scored variant.
Pure function; no LLM.

Intended API:
    def dedup(existing: list[Source], incoming: list[Source]) -> list[Source]: ...

Owner: backend-developer
"""

# TODO(backend-developer): implement dedup().
