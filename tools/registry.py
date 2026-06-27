"""Tool registry: maps active domains -> the tool set bound to the ReAct agent.

This is the single integration point where LangChain ``@tool`` objects are
collected and filtered by the active domain list supplied by the Query Router.
It is also the reroute target when the source grader picks
``mutation_action = "reroute"``.

Domain -> tool policy is mirrored in ``domains/registry.py`` (DOMAIN_POLICY).
Configuration tunables (top_k, timeouts) live in ``config/configuration.yaml``
under ``tools.*``.

Public API (expected by ``agents.react_agent._bind_tools``):
    tools_for(domains: list[str]) -> list[BaseTool]
    all_tools() -> list[BaseTool]

``tools_for`` accepts a list of domain strings (e.g. ``["Techno", "Travel"]``)
and returns the union of tools mapped to each domain.  Unknown domain labels
fall back to the ``GENERIC`` set.  ``all_tools`` returns the full flat list for
diagnostics / reroute fallback.

Owner: backend-developer
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log

# ---------------------------------------------------------------------------
# Lazy imports so registry can be imported even if individual tool modules have
# transient import errors (fail-soft at tool-lookup time, not at import time).
# ---------------------------------------------------------------------------

def _load_tools() -> dict[str, BaseTool]:
    """Import all tool callables and return a name->tool mapping."""
    tool_map: dict[str, BaseTool] = {}
    _import_tool(tool_map, "tools.web_search", "web_search", alias="web")
    _import_tool(tool_map, "tools.wiki", "wikipedia_search", alias="wiki")
    _import_tool(tool_map, "tools.wiki", "wikivoyage_search", alias="wikivoyage")
    _import_tool(tool_map, "tools.arxiv", "arxiv_search", alias="arxiv")
    _import_tool(tool_map, "tools.finance", "finance_ohlcv", alias="finance")
    _import_tool(tool_map, "tools.external_api", "external_api_search", alias="external_api")
    _import_tool(tool_map, "tools.mcp", "mcp_search", alias="mcp")
    return tool_map


def _import_tool(
    tool_map: dict[str, BaseTool],
    module_path: str,
    attr_name: str,
    alias: str,
) -> None:
    """Attempt to import a single tool; log and skip on failure."""
    try:
        import importlib
        mod = importlib.import_module(module_path)
        tool_obj = getattr(mod, attr_name)
        tool_map[alias] = tool_obj
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "tools.registry: could not load tool",
            module=module_path,
            attr=attr_name,
            alias=alias,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Domain -> tool-name mapping  (mirrors domains/registry.py DOMAIN_POLICY)
# ---------------------------------------------------------------------------

#: Maps each canonical domain label to the ordered list of tool aliases it
#: activates.  Tools listed first are preferred (the agent is not forced to
#: call all of them; this is the available set).
DOMAIN_TOOL_MAP: dict[str, list[str]] = {
    "Techno":    ["arxiv", "web", "wiki"],
    "Education": ["wiki", "web"],
    "Travel":    ["wikivoyage", "web"],
    "Art":       ["wiki", "web"],
    "Mgmt":      ["web", "external_api"],
    "Finance":   ["finance", "web"],
    "GENERIC":   ["web", "wiki", "arxiv"],
}

# Populated lazily on first access.
_TOOL_CACHE: dict[str, BaseTool] | None = None


def _get_tools() -> dict[str, BaseTool]:
    global _TOOL_CACHE
    if _TOOL_CACHE is None:
        _TOOL_CACHE = _load_tools()
    return _TOOL_CACHE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tools_for(domains: list[str]) -> list[BaseTool]:
    """Return the union of tools for the given domain labels.

    Args:
        domains: List of active domain labels from the Query Router
                 (e.g. ``["Techno", "Travel"]``).  Unknown labels fall back to
                 ``GENERIC``.

    Returns:
        Deduplicated list of ``BaseTool`` objects bound to the ReAct agent.
        Returns ``[]`` on any error so the caller can degrade gracefully.
    """
    try:
        tool_map = _get_tools()

        wanted_aliases: list[str] = []
        seen: set[str] = set()
        for domain in (domains or ["GENERIC"]):
            aliases = DOMAIN_TOOL_MAP.get(domain) or DOMAIN_TOOL_MAP["GENERIC"]
            for alias in aliases:
                if alias not in seen:
                    seen.add(alias)
                    wanted_aliases.append(alias)

        tools: list[BaseTool] = []
        for alias in wanted_aliases:
            t = tool_map.get(alias)
            if t is not None:
                tools.append(t)
            else:
                log.debug("tools_for: alias not in tool_map, skipping", alias=alias)

        log.info(
            "tools.registry.tools_for",
            domains=domains,
            resolved_aliases=wanted_aliases,
            available=len(tools),
        )
        return tools

    except Exception as exc:
        msg = "tools_for() failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def all_tools() -> list[BaseTool]:
    """Return every tool in the registry (for diagnostics / reroute fallback).

    Returns:
        Flat list of all registered ``BaseTool`` objects.
    """
    try:
        tool_map = _get_tools()
        tools = list(tool_map.values())
        log.debug("tools.registry.all_tools", count=len(tools))
        return tools
    except Exception as exc:
        msg = "all_tools() failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
