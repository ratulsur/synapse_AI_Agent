"""Normalize raw tool hits into typed ``schemas.source.Source`` objects.

Extracts/derives title, author, url, domain, content, and a stable id (content
hash), and attaches the producing tool name.  Pure function; no LLM.

Tools return JSON strings containing list[dict].  The hit dict shape is the
common internal format emitted by every tool in tools/:

    {
        "title":   str,
        "url":     str,
        "content": str,          # article extract / snippet / abstract
        "author":  str | None,
        "score":   float,        # 0.0–1.0 relevance hint from the tool
        "_tool":   str,          # tool name (web / wiki / wikivoyage / arxiv / …)
    }

Any missing key gets a safe default.  A hit with neither url nor title is
dropped.

Owner: backend-developer
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from schemas.source import Source

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize(raw_hits: list[dict], domain: str, tool: str) -> list[Source]:
    """Convert a list of raw hit dicts into typed ``Source`` objects.

    Args:
        raw_hits: List of dicts returned by any retrieval tool (or parsed from
                  a ToolMessage JSON payload).
        domain:   The active retrieval domain label (e.g. ``"Techno"``).
        tool:     Fallback tool name if the hit dict does not contain ``_tool``.

    Returns:
        List of ``Source`` objects; malformed hits are silently skipped with a
        warning log.
    """
    try:
        sources: list[Source] = []
        for hit in raw_hits:
            if not isinstance(hit, dict):
                log.debug("normalize: skipping non-dict hit", type=type(hit).__name__)
                continue
            try:
                source = _hit_to_source(hit, domain=domain, fallback_tool=tool)
                if source is not None:
                    sources.append(source)
            except Exception as exc:  # noqa: BLE001
                log.warning("normalize: skipping malformed hit", error=str(exc))

        log.debug(
            "normalize: done",
            raw=len(raw_hits),
            produced=len(sources),
            domain=domain,
            tool=tool,
        )
        return sources

    except Exception as exc:
        msg = "normalize() failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hit_to_source(hit: dict, domain: str, fallback_tool: str) -> Source | None:
    """Convert one raw hit dict to a ``Source``, or return None to skip."""
    title: str = _coerce_str(
        hit.get("title") or hit.get("name") or ""
    ).strip()

    url: str = _coerce_str(
        hit.get("url") or hit.get("href") or hit.get("link") or ""
    ).strip()

    content: str = _coerce_str(
        hit.get("content")
        or hit.get("body")
        or hit.get("snippet")
        or hit.get("summary")
        or hit.get("extract")
        or ""
    ).strip()

    # Strip HTML tags that may come from Wikipedia excerpts
    content = _strip_html(content)

    author: str | None = _extract_author(hit)

    score_raw: Any = hit.get("score", 0.0)
    try:
        score = float(score_raw)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    effective_tool: str = _coerce_str(
        hit.get("_tool") or fallback_tool or ""
    ).strip()

    # Must have at least a url or title to be useful.
    if not url and not title:
        return None

    # Synthesise a deterministic fake URL when none is present.
    if not url:
        slug = hashlib.sha256(title.encode()).hexdigest()[:12]
        url = f"https://synapse-unknown-source/{slug}"

    return Source(
        title=title or url,
        author=author,
        url=url,
        domain=domain,
        content=content,
        score=score,
        tool=effective_tool or None,
        retrieved_at=datetime.now(tz=timezone.utc),
    )


def _coerce_str(value: Any) -> str:
    """Safely coerce any value to str; return '' on failure."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return ""


def _extract_author(hit: dict) -> str | None:
    """Extract an author string from a hit dict."""
    raw = hit.get("author") or hit.get("authors") or hit.get("author_name")
    if raw is None:
        return None
    if isinstance(raw, list):
        parts = [_coerce_str(a).strip() for a in raw if a]
        text = ", ".join(p for p in parts if p)
    else:
        text = _coerce_str(raw).strip()
    return text if text else None


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove simple HTML/XML tags from a string."""
    return _HTML_TAG_RE.sub("", text).strip()
