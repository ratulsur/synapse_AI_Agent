"""Normalize raw tool hits into typed ``schemas.source.Source`` objects.

Extracts/derives title, author, url, domain, content, and a stable id (content
hash), and attaches the producing tool name. Pure function; no LLM.

Intended API:
    def normalize(raw_hits: list[dict], domain: str, tool: str) -> list[Source]: ...

Owner: backend-developer
"""

# TODO(backend-developer): implement normalize().
