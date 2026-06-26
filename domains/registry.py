"""Domain -> tooling/parameter policy table.

Intended shape:
    DOMAIN_POLICY = {
        'Techno':    {'tools': ['arxiv', 'web', 'mcp'], 'top_k': ...},
        'Education': {'tools': ['wiki', 'web'], ...},
        'Travel':    {'tools': ['wikivoyage', 'web'], ...},
        'Art':       {'tools': ['wiki', 'web'], ...},
        'Mgmt':      {'tools': ['web', 'external_api'], ...},
        'GENERIC':   {'tools': ['web', 'wiki'], ...},   # fallback / reroute target
    }

Single source of truth shared by domains <-> tools.registry <-> query_router.

Owner: backend-developer
"""

# TODO(backend-developer): implement DOMAIN_POLICY.
