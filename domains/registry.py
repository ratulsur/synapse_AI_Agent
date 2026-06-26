"""Domain -> tooling/parameter policy table.

``DOMAIN_POLICY`` is the single source of truth shared between
``tools/registry.py`` and the query router.  Changes here must be reflected in
``tools/registry.py``'s ``DOMAIN_TOOL_MAP`` and ``config/configuration.yaml``'s
``domains`` list.

Canonical domain labels (must match ``schemas/routing.py``):
    Techno, Education, Travel, Art, Mgmt, GENERIC

Owner: backend-developer
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Domain -> tool + retrieval parameter policy
# ---------------------------------------------------------------------------

DOMAIN_POLICY: dict[str, dict] = {
    "Techno": {
        "tools": ["arxiv", "web", "mcp"],
        "top_k": 5,
        "description": "Technology, AI/ML, software engineering, hard sciences.",
    },
    "Education": {
        "tools": ["wiki", "web"],
        "top_k": 4,
        "description": "Pedagogy, curricula, academic concepts, learning resources.",
    },
    "Travel": {
        "tools": ["wikivoyage", "web"],
        "top_k": 4,
        "description": "Travel destinations, logistics, culture, tourism.",
    },
    "Art": {
        "tools": ["wiki", "web"],
        "top_k": 4,
        "description": "Visual art, music, literature, film, cultural commentary.",
    },
    "Mgmt": {
        "tools": ["web", "external_api"],
        "top_k": 5,
        "description": "Business strategy, management theory, finance, economics.",
    },
    "GENERIC": {
        "tools": ["web", "wiki"],
        "top_k": 5,
        "description": "Fallback domain; broad web + Wikipedia coverage.",
    },
}


def policy_for(domain: str) -> dict:
    """Return the policy dict for a domain label, defaulting to GENERIC."""
    return DOMAIN_POLICY.get(domain, DOMAIN_POLICY["GENERIC"])
