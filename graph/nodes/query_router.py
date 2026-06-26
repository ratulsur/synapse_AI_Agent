"""Node: Query Router.

Multi-label router that classifies the query into one or more retrieval
domains (Techno / Education / Travel / Art / Mgmt / GENERIC fallback).

Delegates to ``agents.router_agent``; falls back to ``["GENERIC"]`` if the
agent stub is not yet implemented.

Emits ``route_labels`` (list[str] domain names) and ``active_domains`` (the
same list used downstream by tools.registry and the retrieval subgraph).

Owner: backend-developer (routing prompt/rubric: agent-prompt-engineer)
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.routing import DOMAINS, GENERIC_DOMAIN, RouteLabel


def query_router(state: GraphState) -> dict:
    """Classify the query into one or more retrieval domains.

    Returns a partial state update with keys:
        route_labels   -- list[str]  (domain name strings)
        active_domains -- list[str]  (same; used by retrieval subgraph)
    """
    try:
        query: str = state.get("query", "")
        log.info("query_router: classifying query", query_preview=query[:80])

        # --- Delegate to agent stub ---
        try:
            from agents.router_agent import run_router  # type: ignore[import]
            labels: list[RouteLabel] = run_router(state)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("query_router: router agent stub not ready, falling back to GENERIC")
            labels = [RouteLabel(domain=GENERIC_DOMAIN, confidence=1.0)]

        # Validate all labels and filter to canonical domains.
        valid_labels: list[RouteLabel] = [
            lbl for lbl in labels if lbl.domain in DOMAINS
        ]

        # GENERIC fallback when nothing survived validation.
        if not valid_labels:
            log.warning(
                "query_router: no valid domain labels produced, using GENERIC fallback",
                raw_labels=[lbl.domain for lbl in labels],
            )
            valid_labels = [RouteLabel(domain=GENERIC_DOMAIN, confidence=1.0)]

        active_domains: list[str] = [lbl.domain for lbl in valid_labels]

        log.info(
            "query_router: routing decision",
            active_domains=active_domains,
        )

        return {
            "route_labels": active_domains,
            "active_domains": active_domains,
        }

    except Exception as exc:
        msg = "query_router node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
