"""Tech-blog search tool — site-scoped DuckDuckGo + best-effort article fetch.

Searches Medium, Towards Data Science, KDNuggets, Analytics Vidhya, and
Distill.pub using DuckDuckGo's site: operator, then optionally fetches and
strips article HTML for fuller content (falls back to the DuckDuckGo snippet
when a page is paywalled, redirects, or times out).

Hit schema returned by this tool:
    {"title": str, "url": str, "content": str, "author": null, "score": float, "_tool": "tech_blogs"}

Owner: Ratul Sur
"""

from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser

from langchain_core.tools import tool

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config

# ---------------------------------------------------------------------------
# Site scope
# ---------------------------------------------------------------------------

_SITES = [
    "medium.com",
    "towardsdatascience.com",
    "kdnuggets.com",
    "analyticsvidhya.com",
    "distill.pub",
]

_SITE_FILTER = " OR ".join(f"site:{s}" for s in _SITES)

# ---------------------------------------------------------------------------
# Minimal HTML stripper (stdlib only — no BeautifulSoup dependency)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "head", "nav", "footer", "aside", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self, max_chars: int = 3000) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s{2,}", " ", raw)[:max_chars]


def _fetch_article_text(url: str, timeout: int) -> str | None:
    """GET url, strip HTML, return plain text. Returns None on any failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; SynapseResearchBot/1.0; "
                    "+https://github.com/ratulsur/synapse_AI_Agent)"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None
            html = resp.read(65_536).decode("utf-8", errors="ignore")

        parser = _TextExtractor()
        parser.feed(html)
        text = parser.get_text()
        return text if len(text) > 100 else None

    except Exception as exc:
        log.debug("tech_blog_search._fetch_article_text: skipped", url=url, reason=str(exc))
        return None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def tech_blog_search(query: str) -> str:
    """Search popular data science and ML tech blogs (Medium, TDS, KDNuggets, etc.).

    Scopes DuckDuckGo to Medium, Towards Data Science, KDNuggets, Analytics
    Vidhya, and Distill.pub. Best for practical tutorials, opinion pieces, and
    applied ML content not typically found on arXiv.

    Args:
        query: The search query string.

    Returns:
        JSON string — list of hit dicts with keys:
        title, url, content, author, score, _tool.
        Returns "[]" on any error so the graph does not crash.
    """
    try:
        cfg = load_config()
        tool_cfg = cfg.get("tools", {}).get("tech_blogs", {})
        top_k: int = int(tool_cfg.get("top_k", 5))
        timeout: int = int(tool_cfg.get("timeout", 10))
        fetch_timeout: int = int(tool_cfg.get("fetch_timeout", 5))
        fetch_content: bool = bool(tool_cfg.get("fetch_content", True))

        from ddgs import DDGS  # type: ignore[import]

        scoped_query = f"({_SITE_FILTER}) {query}"
        log.info("tech_blog_search: querying", query_preview=query[:60], top_k=top_k)

        with DDGS(timeout=timeout) as ddgs:
            raw = list(ddgs.text(scoped_query, max_results=top_k))

        hits = []
        for r in raw:
            url = r.get("href", "")
            snippet = r.get("body", "")

            if fetch_content and url:
                fetched = _fetch_article_text(url, timeout=fetch_timeout)
                content = fetched if fetched else snippet
            else:
                content = snippet

            hits.append({
                "title": r.get("title", ""),
                "url": url,
                "content": content,
                "author": None,
                "score": 0.75,
                "_tool": "tech_blogs",
            })

        log.info("tech_blog_search: results", count=len(hits))
        return json.dumps(hits)

    except ImportError:
        log.warning("tech_blog_search: ddgs not installed; returning empty results")
        return json.dumps([])
    except Exception as exc:  # noqa: BLE001 — fail-soft so graph survives
        log.warning("tech_blog_search: failed", error=str(exc))
        return json.dumps([])
