"""MCP (Model Context Protocol) tool client.

Connects to configured MCP servers and surfaces their tools to the ReAct agent.
Server endpoints are configured via ``config/configuration.yaml`` under
``tools.mcp.servers``.

Until at least one MCP server is configured, the tool returns an empty result
gracefully rather than crashing the graph.

To wire a real MCP server:
1. Add an entry to ``tools.mcp.servers`` in ``config/configuration.yaml``:
       tools:
         mcp:
           enabled: true
           servers:
             - name: "my-mcp-server"
               url: "http://localhost:8765"
               transport: "http"
2. Install the ``mcp`` Python SDK (``pip install mcp``).
3. Replace the stub body with real MCP client calls.

Hit schema when real data is present:
    {"title": str, "url": str, "content": str, "author": null,
     "score": float, "_tool": "mcp"}

Owner: backend-developer
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config


@tool
def mcp_search(query: str) -> str:
    """Search via configured MCP (Model Context Protocol) servers.

    Currently a graceful stub: returns an empty result list until at least one
    MCP server is listed under ``tools.mcp.servers`` in configuration.yaml.

    Args:
        query: The search query forwarded to the MCP server.

    Returns:
        JSON string — list of hit dicts, or ``"[]"`` when no servers are
        configured or any error occurs.
    """
    try:
        cfg = load_config()
        mcp_cfg = cfg.get("tools", {}).get("mcp", {})
        enabled: bool = mcp_cfg.get("enabled", False)
        servers: list = mcp_cfg.get("servers", [])

        if not enabled or not servers:
            log.debug(
                "mcp_search: no MCP servers configured (tools.mcp.enabled=false or servers=[])"
            )
            return json.dumps([])

        # --- Placeholder for real MCP client implementation ---
        # Example pattern using the ``mcp`` SDK:
        #   from mcp import ClientSession, StdioServerParameters
        #   from mcp.client.stdio import stdio_client
        #   async with stdio_client(server_params) as (read, write):
        #       async with ClientSession(read, write) as session:
        #           result = await session.call_tool("search", {"query": query})
        #           hits = [...parse result...]
        #           return json.dumps(hits)

        log.warning(
            "mcp_search: enabled but no implementation; returning empty results",
            servers=[s.get("name") for s in servers],
        )
        return json.dumps([])

    except Exception as exc:  # noqa: BLE001
        log.warning("mcp_search: failed", error=str(exc))
        return json.dumps([])
