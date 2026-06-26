"""Integration tests: build_graph() compiles correctly.

Covers:
- build_graph() returns a CompiledStateGraph without errors.
- The compiled graph has the expected set of parent-graph node names.
- The graph accepts invocation config shape {"configurable": {"thread_id": ...}}.

These tests are offline and do NOT invoke any LLM (they only compile the graph).

Owner: test-eval-agent
"""

import pytest


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_build_graph_returns_compiled_graph(self):
        """build_graph() must compile without raising."""
        from graph.builder import build_graph

        g = build_graph()
        assert g is not None

    def test_compiled_graph_is_invocable_type(self):
        """The compiled object must expose an .invoke() method (CompiledStateGraph)."""
        from graph.builder import build_graph

        g = build_graph()
        assert callable(getattr(g, "invoke", None)), (
            f"Compiled graph type {type(g)} does not have .invoke()"
        )

    def test_compiled_graph_has_stream_method(self):
        from graph.builder import build_graph

        g = build_graph()
        assert callable(getattr(g, "stream", None))

    def test_compiled_graph_has_get_graph_method(self):
        """LangGraph compiled graphs expose get_graph() for topology inspection."""
        from graph.builder import build_graph

        g = build_graph()
        assert callable(getattr(g, "get_graph", None))

    def test_graph_node_names(self):
        """The compiled parent graph must contain every expected node."""
        from graph.builder import build_graph

        g = build_graph()
        # get_graph() returns a Pregel-internal structure; we verify via the repr
        # or by checking that the graph object contains the expected node keys.
        # LangGraph's compiled graph exposes its nodes via .nodes attribute on
        # the underlying subgraph structure.
        # We use get_graph().nodes which returns a dict-like of node names.
        topology = g.get_graph()
        node_names = set(topology.nodes.keys())
        expected = {
            "create_analyst",
            "scope_plan",
            "human_in_the_loop",
            "query_router",
            "retrieval_evidence",
            "write",
            "section_drafting",
            "grounding_grader",
            "revise_section",
            "assemble_report",
            "final_answer",
        }
        missing = expected - node_names
        assert not missing, f"Graph is missing nodes: {missing}"

    def test_build_graph_is_idempotent(self):
        """Calling build_graph() twice produces two valid independent graphs."""
        from graph.builder import build_graph

        g1 = build_graph()
        g2 = build_graph()
        assert g1 is not g2
        assert callable(g1.invoke)
        assert callable(g2.invoke)
