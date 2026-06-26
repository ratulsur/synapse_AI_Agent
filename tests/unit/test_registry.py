"""Unit tests for tools/registry.py.

Covers:
- DOMAIN_TOOL_MAP contains an entry for every canonical DOMAINS value.
- tools_for() returns a list (may be empty if tool imports fail, but never raises).
- tools_for([]) defaults to GENERIC tools.
- tools_for(["UnknownDomain"]) falls back to GENERIC tools.
- tools_for(["Techno"]) resolves arxiv, web, wiki aliases (no network calls).
- all_tools() returns a list (non-raising).
- Return types from tools_for/all_tools are BaseTool instances when tool modules load.
- No network calls are made (tools are registered, not invoked).

Owner: test-eval-agent
"""

import pytest
from langchain_core.tools import BaseTool

from schemas.routing import DOMAINS
from tools.registry import DOMAIN_TOOL_MAP, all_tools, tools_for


# ---------------------------------------------------------------------------
# DOMAIN_TOOL_MAP structure
# ---------------------------------------------------------------------------


class TestDomainToolMap:
    def test_all_canonical_domains_have_entries(self):
        """Every domain in DOMAINS must have a key in DOMAIN_TOOL_MAP."""
        for domain in DOMAINS:
            assert domain in DOMAIN_TOOL_MAP, f"Missing entry for domain '{domain}'"

    def test_generic_fallback_exists(self):
        assert "GENERIC" in DOMAIN_TOOL_MAP
        assert len(DOMAIN_TOOL_MAP["GENERIC"]) > 0

    def test_techno_has_arxiv(self):
        assert "arxiv" in DOMAIN_TOOL_MAP["Techno"]

    def test_travel_has_wikivoyage(self):
        assert "wikivoyage" in DOMAIN_TOOL_MAP["Travel"]

    def test_all_entries_are_lists_of_strings(self):
        for domain, aliases in DOMAIN_TOOL_MAP.items():
            assert isinstance(aliases, list), f"{domain} entry is not a list"
            for alias in aliases:
                assert isinstance(alias, str), f"Non-string alias in {domain}: {alias!r}"


# ---------------------------------------------------------------------------
# tools_for() -- structural guarantees
# ---------------------------------------------------------------------------


class TestToolsFor:
    def test_returns_list_for_generic(self):
        result = tools_for(["GENERIC"])
        assert isinstance(result, list)

    def test_returns_list_for_techno(self):
        result = tools_for(["Techno"])
        assert isinstance(result, list)

    def test_returns_list_for_travel(self):
        result = tools_for(["Travel"])
        assert isinstance(result, list)

    def test_empty_domains_defaults_to_generic_tools(self):
        """Empty domain list should fall back to GENERIC tool set."""
        empty_result = tools_for([])
        generic_result = tools_for(["GENERIC"])
        # Both should return the same tools (GENERIC fallback)
        empty_names = {t.name for t in empty_result}
        generic_names = {t.name for t in generic_result}
        assert empty_names == generic_names

    def test_unknown_domain_falls_back_to_generic(self):
        """Unknown domain strings are treated as GENERIC."""
        unknown_result = tools_for(["UnknownDomainXYZ"])
        generic_result = tools_for(["GENERIC"])
        unknown_names = {t.name for t in unknown_result}
        generic_names = {t.name for t in generic_result}
        assert unknown_names == generic_names

    def test_return_values_are_base_tools(self):
        """Every returned element must be a BaseTool instance."""
        for domain in DOMAINS:
            result = tools_for([domain])
            for tool in result:
                assert isinstance(tool, BaseTool), (
                    f"tools_for([{domain!r}]) returned a non-BaseTool: {type(tool)}"
                )

    def test_multi_domain_union_no_duplicates(self):
        """Union of two domains: tool names should be deduplicated."""
        techno_tools = {t.name for t in tools_for(["Techno"])}
        education_tools = {t.name for t in tools_for(["Education"])}
        combined_result = tools_for(["Techno", "Education"])
        combined_names = {t.name for t in combined_result}
        # Combined result should be the union of the individual sets
        assert combined_names == techno_tools | education_tools

    def test_tools_for_does_not_raise_on_any_domain(self):
        """tools_for must not raise for any canonical domain."""
        for domain in DOMAINS:
            try:
                result = tools_for([domain])
                assert isinstance(result, list)
            except Exception as exc:
                pytest.fail(f"tools_for([{domain!r}]) raised: {exc}")

    def test_no_duplicate_tools_within_single_domain(self):
        """A single-domain call should never return the same tool twice."""
        for domain in DOMAINS:
            result = tools_for([domain])
            names = [t.name for t in result]
            assert len(names) == len(set(names)), (
                f"Duplicate tools returned for domain {domain!r}: {names}"
            )


# ---------------------------------------------------------------------------
# all_tools()
# ---------------------------------------------------------------------------


class TestAllTools:
    def test_all_tools_returns_list(self):
        result = all_tools()
        assert isinstance(result, list)

    def test_all_tools_returns_base_tools(self):
        for tool in all_tools():
            assert isinstance(tool, BaseTool)

    def test_all_tools_does_not_raise(self):
        try:
            all_tools()
        except Exception as exc:
            pytest.fail(f"all_tools() raised: {exc}")

    def test_all_tools_superset_of_any_domain(self):
        """all_tools() should contain at least as many tools as any single domain."""
        all_names = {t.name for t in all_tools()}
        for domain in DOMAINS:
            domain_names = {t.name for t in tools_for([domain])}
            assert domain_names.issubset(all_names), (
                f"all_tools() is missing tools for domain {domain!r}: "
                f"{domain_names - all_names}"
            )
