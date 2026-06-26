"""Wikipedia and Wikivoyage tools — keyless retrieval via REST APIs.

``wikipedia_search`` — used for Education / Art / Mgmt / general-knowledge queries.
``wikivoyage_search`` — used specifically for Travel-domain queries.

Both tools use the respective MediaWiki REST v1 search API (no authentication
required) followed by a summary fetch for each result.  Return a JSON string of
``list[dict]`` in the common internal hit format.

Hit schema:
    {"title": str, "url": str, "content": str, "author": null, "score": float, "_tool": "wiki"|"wikivoyage"}

Owner: backend-developer
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from langchain_core.tools import tool

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config

_USER_AGENT = "synapse-ai-agent/0.1.0 (research agent; contact: ratulsur@gmail.com)"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

@tool
def wikipedia_search(query: str) -> str:
    """Search Wikipedia for encyclopaedic / factual information.

    Args:
        query: The search query string.

    Returns:
        JSON string — list of hit dicts with keys:
        title, url, content, author, score, _tool.
        Returns ``"[]"`` on any error so the graph does not crash.
    """
    try:
        hits = _wiki_search(
            query=query,
            base_host="en.wikipedia.org",
            tool_name="wiki",
        )
        log.info("wikipedia_search: results", count=len(hits))
        return json.dumps(hits)
    except Exception as exc:  # noqa: BLE001
        log.warning("wikipedia_search: failed", error=str(exc))
        return json.dumps([])


# ---------------------------------------------------------------------------
# Wikivoyage
# ---------------------------------------------------------------------------

@tool
def wikivoyage_search(query: str) -> str:
    """Search Wikivoyage for travel destination information.

    Args:
        query: The travel-related search query string.

    Returns:
        JSON string — list of hit dicts with keys:
        title, url, content, author, score, _tool.
        Returns ``"[]"`` on any error so the graph does not crash.
    """
    try:
        hits = _wiki_search(
            query=query,
            base_host="en.wikivoyage.org",
            tool_name="wikivoyage",
        )
        log.info("wikivoyage_search: results", count=len(hits))
        return json.dumps(hits)
    except Exception as exc:  # noqa: BLE001
        log.warning("wikivoyage_search: failed", error=str(exc))
        return json.dumps([])


# ---------------------------------------------------------------------------
# Shared implementation
# ---------------------------------------------------------------------------

def _wiki_search(
    query: str,
    base_host: str,
    tool_name: str,
) -> list[dict]:
    """Search a MediaWiki site and fetch summaries for the top results."""
    cfg = load_config()
    top_k: int = int(cfg.get("tools", {}).get("wiki", {}).get("top_k", 3))
    timeout: int = int(cfg.get("tools", {}).get("wiki", {}).get("timeout", 10))

    # Step 1: search for page titles
    encoded_q = urllib.parse.quote(query)
    search_url = (
        f"https://{base_host}/w/rest.php/v1/search/page"
        f"?q={encoded_q}&limit={top_k}"
    )
    search_data = _fetch_json(search_url, timeout)
    pages: list[dict] = search_data.get("pages", [])

    if not pages:
        log.debug("_wiki_search: no pages found", host=base_host, query=query)
        return []

    hits: list[dict] = []
    for page in pages:
        key: str = page.get("key", "") or page.get("title", "")
        title: str = page.get("title", key)
        if not key:
            continue

        # Step 2: fetch the page summary for content
        encoded_key = urllib.parse.quote(key)
        summary_url = f"https://{base_host}/api/rest_v1/page/summary/{encoded_key}"
        try:
            summary_data = _fetch_json(summary_url, timeout)
            content = summary_data.get("extract", "") or ""
            canonical_url = (
                summary_data.get("content_urls", {})
                .get("desktop", {})
                .get("page", "")
                or f"https://{base_host}/wiki/{encoded_key}"
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("_wiki_search: summary fetch failed", key=key, error=str(exc))
            content = _strip_html(page.get("excerpt", ""))
            canonical_url = f"https://{base_host}/wiki/{encoded_key}"

        content = _strip_html(content)

        hits.append(
            {
                "title": title,
                "url": canonical_url,
                "content": content,
                "author": None,
                "score": 0.75,
                "_tool": tool_name,
            }
        )

    return hits


def _fetch_json(url: str, timeout: int) -> dict:
    """Fetch a URL and return the parsed JSON body."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw: bytes = resp.read()
    return json.loads(raw)


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()
