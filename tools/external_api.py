"""External-API tool adapters (Mgmt domain supplement).

Home for domain-specific REST/data API tools (finance, datasets, news, etc.)
that require API keys.  Until credentials are configured, every tool here
fails gracefully with an empty result rather than crashing the graph.

To wire a real API:
1. Add an API key to ``.env`` and load it via ``utils.model_loader.ApiKeyManager``.
2. Add a config block under ``tools.external_api`` in ``config/configuration.yaml``.
3. Replace the stub body with the real HTTP call.

Hit schema returned when real data is present:
    {"title": str, "url": str, "content": str, "author": str|null,
     "score": float, "_tool": "external_api"}

Owner: backend-developer
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config


@tool
def external_api_search(query: str) -> str:
    """Search configured external data APIs (requires credentials).

    Currently a graceful stub: returns an empty result list until API keys are
    provided in the environment.

    Args:
        query: The search query string.

    Returns:
        JSON string — list of hit dicts, or ``"[]"`` when no credentials are
        configured or any error occurs.
    """
    try:
        cfg = load_config()
        enabled: bool = cfg.get("tools", {}).get("external_api", {}).get("enabled", False)

        if not enabled:
            log.debug(
                "external_api_search: disabled in config (tools.external_api.enabled=false)"
            )
            return json.dumps([])

        # --- Placeholder for a real implementation ---
        # Example pattern:
        #   from utils.model_loader import ApiKeyManager
        #   key = ApiKeyManager().some_api_key
        #   response = requests.get("https://api.example.com/search", ...)
        #   hits = [{"title": ..., "url": ..., ...} for item in response.json()]
        #   return json.dumps(hits)

        log.warning(
            "external_api_search: enabled but no implementation; returning empty results"
        )
        return json.dumps([])

    except Exception as exc:  # noqa: BLE001
        log.warning("external_api_search: failed", error=str(exc))
        return json.dumps([])
