"""ReAct tool layer + evidence-processing functions.

Retrieval tools (web / wiki+wikivoyage / arXiv / external APIs / MCP) are exposed
to the ReAct agent through ``tools.registry``. The deterministic post-processing
functions (normalize, dedup) live in ``tools.processing``.

Owner: backend-developer
"""
