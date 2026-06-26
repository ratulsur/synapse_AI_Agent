"""Web search tool — keyless DuckDuckGo retrieval (GENERIC fallback + broad coverage).

Uses the ``ddgs`` package (formerly ``duckduckgo_search``) which requires no
API key.  Returns a JSON string containing ``list[dict]`` in the common internal
hit format understood by ``tools.processing.normalize``.

Hit schema returned by this tool:
    {"title": str, "url": str, "content": str, "author": null, "score": float, "_tool": "web"}

Owner: backend-developer
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config


@tool
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo (no API key required).

    Args:
        query: The search query string.

    Returns:
        JSON string — a list of hit dicts with keys:
        title, url, content, author, score, _tool.
        Returns ``"[]"`` on any error so the graph does not crash.
    """
    try:
        cfg = load_config()
        top_k: int = int(
            cfg.get("tools", {}).get("web_search", {}).get("top_k", 5)
        )
        timeout: int = int(
            cfg.get("tools", {}).get("web_search", {}).get("timeout", 10)
        )

        from ddgs import DDGS  # type: ignore[import]

        log.info("web_search: querying DuckDuckGo", query_preview=query[:60], top_k=top_k)

        with DDGS(timeout=timeout) as ddgs:
            raw = list(ddgs.text(query, max_results=top_k))

        hits = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "content": r.get("body", ""),
                "author": None,
                "score": 0.7,
                "_tool": "web",
            }
            for r in raw
        ]

        log.info("web_search: results", count=len(hits))
        return json.dumps(hits)

    except ImportError:
        log.warning("web_search: ddgs package not installed; returning empty results")
        return json.dumps([])
    except Exception as exc:  # noqa: BLE001 — fail-soft so graph survives
        log.warning("web_search: query failed", error=str(exc))
        return json.dumps([])
