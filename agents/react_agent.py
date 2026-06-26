"""Agent: ReAct tool-use agent for the retrieval loop.

Reason-act-observe loop over the bound tool set from ``tools.registry`` (web,
wiki/wikivoyage, arXiv, external APIs, MCP), scoped to the active domains. Emits
raw retrieval hits for the normalize step plus its message scratch. Honors the
mutation_action on re-entry (reformulate / widen / reroute).

Prompt: prompts.react.

Owner: agent-prompt-engineer (tool bindings: backend-developer)
"""

# TODO(agent-prompt-engineer): build ReAct agent bound to tools.registry.
