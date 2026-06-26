"""Tool registry: maps domains -> the tool set bound to the ReAct agent.

Single place where LangChain ``@tool`` objects are collected and filtered by
active domain (so a Travel query binds wikivoyage, a Techno query binds arXiv,
GENERIC binds web+wiki). Also the integration point for ``reroute`` mutations.

Intended API:
    def tools_for(domains: list[str]) -> list[BaseTool]: ...
    def all_tools() -> list[BaseTool]: ...

Owner: backend-developer
"""

# TODO(backend-developer): implement domain->tool registry.
