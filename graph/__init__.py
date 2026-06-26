"""LangGraph wiring layer for the Synapse research-report agent.

Owns the StateGraph definition, the top-level state schema, node callables,
conditional-edge routers, and the two subgraphs (retrieval/evidence loop and
parallel section drafting). This package is the orchestration backbone that
stitches the agents, tools, schemas, and persistence layers together.

Owner: backend-developer
"""
