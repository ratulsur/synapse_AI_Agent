"""Agent layer: LLM-backed reasoning units invoked by graph nodes.

Each agent wraps a prompt (from ``prompts/``) + an LLM (from
``utils.model_loader.ModelLoader``) + an output schema (from ``schemas/``). Agents
contain no graph wiring; they are called by ``graph.nodes`` / subgraphs.

Owner: Ratul Sur
"""
