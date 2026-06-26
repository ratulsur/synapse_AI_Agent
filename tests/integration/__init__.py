"""Integration tests: graph wiring, subgraph loops, checkpoint resume, interrupts.

Mock or record LLM/tool calls so the topology and termination conditions of both
feedback loops are exercised deterministically.

Owner: Ratul Sur
"""
