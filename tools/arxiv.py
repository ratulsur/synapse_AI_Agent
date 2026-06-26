"""arXiv tool — keyless scientific-paper retrieval (Techno domain).

Uses the ``arxiv`` package (v4.x) which wraps the public arXiv API.  No API
key is required.  Returns a JSON string of ``list[dict]`` in the common
internal hit format.

Hit schema:
    {"title": str, "url": str, "content": str, "author": str|null, "score": float, "_tool": "arxiv"}

Owner: backend-developer
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config


@tool
def arxiv_search(query: str) -> str:
    """Search arXiv for scientific papers and preprints.

    Args:
        query: The research query string (e.g. ``"transformer neural networks"``).

    Returns:
        JSON string — list of hit dicts with keys:
        title, url, content, author, score, _tool.
        Returns ``"[]"`` on any error so the graph does not crash.
    """
    try:
        import arxiv  # type: ignore[import]

        cfg = load_config()
        top_k: int = int(cfg.get("tools", {}).get("arxiv", {}).get("top_k", 5))
        timeout: int = int(cfg.get("tools", {}).get("arxiv", {}).get("timeout", 15))

        log.info("arxiv_search: querying arXiv", query_preview=query[:60], top_k=top_k)

        client = arxiv.Client(num_retries=2, delay_seconds=1.0)
        search = arxiv.Search(
            query=query,
            max_results=top_k,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        hits: list[dict] = []
        for result in client.results(search):
            authors = [a.name for a in (result.authors or [])]
            author_str = ", ".join(authors[:3])
            if len(authors) > 3:
                author_str += " et al."

            hits.append(
                {
                    "title": result.title or "",
                    "url": result.entry_id or "",
                    "content": (result.summary or "").strip(),
                    "author": author_str or None,
                    "score": 0.85,
                    "_tool": "arxiv",
                }
            )

        log.info("arxiv_search: results", count=len(hits))
        return json.dumps(hits)

    except ImportError:
        log.warning("arxiv_search: arxiv package not installed; returning empty results")
        return json.dumps([])
    except Exception as exc:  # noqa: BLE001
        log.warning("arxiv_search: query failed", error=str(exc))
        return json.dumps([])
