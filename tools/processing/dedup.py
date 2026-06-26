"""Deduplicate Source[] by url and content hash.

Merges ``existing`` and ``incoming`` Source lists, keeping each unique source
exactly once.  Duplicate detection uses two keys in order:

1. ``Source.id``  — the stable SHA-256 content hash already on the object.
2. ``Source.url`` — catches cases where two tools return the same page with
   slightly different snippets (different ids but same canonical URL).

When a duplicate is detected the version already in ``existing`` is kept
(first-seen wins).  Order of the returned list is: existing (unchanged) then
truly-new from incoming (in their original order).

Pure function; no I/O, no LLM.

Owner: backend-developer
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from schemas.source import Source


def dedup(existing: list[Source], incoming: list[Source]) -> list[Source]:
    """Return ``existing`` extended with non-duplicate items from ``incoming``.

    Args:
        existing: Sources already accumulated in the graph state.
        incoming: Candidate new sources produced in the current retrieval step.

    Returns:
        A new list with existing sources first, then truly-new sources from
        incoming.  The original lists are not mutated.
    """
    try:
        if not incoming:
            return list(existing)

        seen_ids: set[str] = {s.id for s in existing}
        # Normalise URLs for comparison: strip trailing slash, lower-case scheme/host.
        seen_urls: set[str] = {_norm_url(s.url) for s in existing if s.url}

        truly_new: list[Source] = []
        for src in incoming:
            if src.id in seen_ids:
                log.debug("dedup: skip id-duplicate", id=src.id, url=src.url)
                continue
            norm = _norm_url(src.url)
            if norm and norm in seen_urls:
                log.debug("dedup: skip url-duplicate", url=src.url)
                continue
            seen_ids.add(src.id)
            if norm:
                seen_urls.add(norm)
            truly_new.append(src)

        log.debug(
            "dedup: done",
            existing=len(existing),
            incoming=len(incoming),
            new=len(truly_new),
            dropped=len(incoming) - len(truly_new),
        )
        return list(existing) + truly_new

    except Exception as exc:
        msg = "dedup() failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm_url(url: str) -> str:
    """Normalise a URL string for comparison (lowercase, no trailing slash)."""
    if not url:
        return ""
    # Strip fragments, normalise whitespace, lowercase
    cleaned = url.split("#")[0].strip().lower().rstrip("/")
    return cleaned
