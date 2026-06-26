"""Routing labels and the canonical domain set.

DOMAINS is the authoritative list shared between schemas, domains/registry.py,
and graph/routers.py.  GENERIC is the fallback used when no specific label fires
or on a reroute mutation.

Owner: Ratul Sur
"""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Canonical domain list -- single source of truth.
# Any changes here must be reflected in domains/registry.py and
# config/configuration.yaml (agent.domains).
# ---------------------------------------------------------------------------
DOMAINS: list[str] = ["Techno", "Education", "Travel", "Art", "Mgmt", "GENERIC"]

GENERIC_DOMAIN: str = "GENERIC"


class RouteLabel(BaseModel):
    """A single domain classification label produced by the Query Router.

    The router may emit several RouteLabels (multi-label); the graph uses the
    ``active_domains`` list (derived from these labels) to select which tool
    sets to call.
    """

    domain: str = Field(
        description=f"One of the canonical domains: {DOMAINS}."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Router confidence in this label (0..1).",
    )

    def is_valid(self) -> bool:
        """Return True if the domain is in the canonical DOMAINS list."""
        return self.domain in DOMAINS
