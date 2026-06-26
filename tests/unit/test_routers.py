"""Unit tests for graph/routers.py conditional-edge functions.

Covers:
- route_after_human: approve -> "query_router", not-approve -> "scope_plan".
- route_query: unconditionally "retrieval_evidence".
- route_after_source_grader:
    pass -> END,
    fail + iter < max -> "tool_calls",
    fail + iter >= max -> END (loop-termination cap enforced),
    no grade + under cap -> "tool_calls" (safe default),
    no grade + at cap -> END.
- route_after_grounding_grader:
    no grade -> "assemble_report",
    passing grade with no failing_ids -> "assemble_report",
    failing_ids + iter < max -> "revise_section",
    failing_ids + iter >= max -> "assemble_report" (loop-termination cap enforced).

Owner: test-eval-agent
"""

import pytest
from langgraph.graph import END

from graph.routers import (
    route_after_grounding_grader,
    route_after_human,
    route_after_source_grader,
    route_query,
)
from schemas.grading import GraderVerdict, MutationAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _passing_verdict(**kwargs) -> GraderVerdict:
    return GraderVerdict(passed=True, score=0.9, **kwargs)


def _failing_verdict(**kwargs) -> GraderVerdict:
    return GraderVerdict(passed=False, score=0.2, mutation_action=MutationAction.REFORMULATE, **kwargs)


# ---------------------------------------------------------------------------
# route_after_human
# ---------------------------------------------------------------------------


class TestRouteAfterHuman:
    def test_approved_routes_to_query_router(self):
        state = {"plan_approved": True}
        assert route_after_human(state) == "query_router"

    def test_not_approved_routes_to_scope_plan(self):
        state = {"plan_approved": False}
        assert route_after_human(state) == "scope_plan"

    def test_missing_key_defaults_to_scope_plan(self):
        """When plan_approved is absent, default is False -> scope_plan."""
        assert route_after_human({}) == "scope_plan"

    def test_none_value_defaults_to_scope_plan(self):
        assert route_after_human({"plan_approved": None}) == "scope_plan"


# ---------------------------------------------------------------------------
# route_query
# ---------------------------------------------------------------------------


class TestRouteQuery:
    def test_always_routes_to_retrieval_evidence(self):
        assert route_query({}) == "retrieval_evidence"
        assert route_query({"active_domains": ["Techno"]}) == "retrieval_evidence"
        assert route_query({"active_domains": ["GENERIC"]}) == "retrieval_evidence"
        assert route_query({"active_domains": ["Travel", "Education"]}) == "retrieval_evidence"


# ---------------------------------------------------------------------------
# route_after_source_grader
# ---------------------------------------------------------------------------


class TestRouteAfterSourceGrader:
    # --- Pass cases ---

    def test_passed_grade_exits_subgraph(self):
        state = {
            "source_grade": _passing_verdict(),
            "retrieval_iteration": 1,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == END

    def test_passed_grade_exits_even_at_cap(self):
        """A passing grade exits the loop regardless of iteration count."""
        state = {
            "source_grade": _passing_verdict(),
            "retrieval_iteration": 3,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == END

    # --- Fail cases, under cap ---

    def test_failing_under_cap_routes_to_tool_calls(self):
        state = {
            "source_grade": _failing_verdict(),
            "retrieval_iteration": 1,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == "tool_calls"

    def test_failing_at_cap_minus_one_routes_to_tool_calls(self):
        """One iteration below the cap still loops back."""
        state = {
            "source_grade": _failing_verdict(),
            "retrieval_iteration": 2,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == "tool_calls"

    # --- Fail cases, at/beyond cap (termination) ---

    def test_failing_at_cap_exits_subgraph(self):
        """TERMINATION CAP: at iteration == max, exit to END (not loop back)."""
        state = {
            "source_grade": _failing_verdict(),
            "retrieval_iteration": 3,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == END

    def test_failing_above_cap_exits_subgraph(self):
        """Even past the cap (shouldn't normally happen), exit to END."""
        state = {
            "source_grade": _failing_verdict(),
            "retrieval_iteration": 5,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == END

    def test_cap_of_one_exits_after_first_iteration(self):
        """With cap=1, a single failing iteration should exit."""
        state = {
            "source_grade": _failing_verdict(),
            "retrieval_iteration": 1,
            "max_retrieval_iterations": 1,
        }
        assert route_after_source_grader(state) == END

    # --- No grade yet ---

    def test_no_grade_under_cap_routes_to_tool_calls(self):
        """No grade yet treated as failing; loops if under cap."""
        state = {
            "source_grade": None,
            "retrieval_iteration": 0,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == "tool_calls"

    def test_no_grade_missing_key_under_cap(self):
        """Missing source_grade key also treated as no grade."""
        state = {"retrieval_iteration": 0, "max_retrieval_iterations": 3}
        assert route_after_source_grader(state) == "tool_calls"

    def test_no_grade_at_cap_exits(self):
        """No grade at cap -> exit instead of infinite loop."""
        state = {
            "retrieval_iteration": 3,
            "max_retrieval_iterations": 3,
        }
        assert route_after_source_grader(state) == END

    # --- Default cap behavior ---

    def test_default_max_is_three(self):
        """When max_retrieval_iterations is absent, default is 3."""
        # iter=2 < default max=3 -> tool_calls
        state = {
            "source_grade": _failing_verdict(),
            "retrieval_iteration": 2,
        }
        assert route_after_source_grader(state) == "tool_calls"

        # iter=3 >= default max=3 -> END
        state["retrieval_iteration"] = 3
        assert route_after_source_grader(state) == END


# ---------------------------------------------------------------------------
# route_after_grounding_grader
# ---------------------------------------------------------------------------


class TestRouteAfterGroundingGrader:
    # --- No grade yet ---

    def test_no_grade_routes_to_assemble_report(self):
        assert route_after_grounding_grader({}) == "assemble_report"

    def test_none_grade_routes_to_assemble_report(self):
        assert route_after_grounding_grader({"grounding_grade": None}) == "assemble_report"

    # --- Passing / all grounded ---

    def test_passing_no_failing_ids_routes_to_assemble(self):
        state = {
            "grounding_grade": _passing_verdict(failing_section_ids=[]),
            "revise_iteration": 0,
            "max_revise_iterations": 2,
        }
        assert route_after_grounding_grader(state) == "assemble_report"

    def test_passing_with_empty_failing_ids_routes_to_assemble(self):
        """Explicit empty list means all sections passed."""
        state = {
            "grounding_grade": GraderVerdict(passed=True, failing_section_ids=[]),
            "revise_iteration": 1,
            "max_revise_iterations": 2,
        }
        assert route_after_grounding_grader(state) == "assemble_report"

    # --- Failing, under cap ---

    def test_failing_sections_under_cap_routes_to_revise(self):
        state = {
            "grounding_grade": GraderVerdict(
                passed=False, failing_section_ids=["body"]
            ),
            "revise_iteration": 0,
            "max_revise_iterations": 2,
        }
        assert route_after_grounding_grader(state) == "revise_section"

    def test_multiple_failing_sections_under_cap(self):
        state = {
            "grounding_grade": GraderVerdict(
                passed=False, failing_section_ids=["intro", "conclusion"]
            ),
            "revise_iteration": 1,
            "max_revise_iterations": 2,
        }
        assert route_after_grounding_grader(state) == "revise_section"

    # --- Failing, at/beyond cap (termination) ---

    def test_failing_at_cap_routes_to_assemble_report(self):
        """TERMINATION CAP: at revise_iteration == max, assemble with best draft."""
        state = {
            "grounding_grade": GraderVerdict(
                passed=False, failing_section_ids=["body"]
            ),
            "revise_iteration": 2,
            "max_revise_iterations": 2,
        }
        assert route_after_grounding_grader(state) == "assemble_report"

    def test_failing_above_cap_routes_to_assemble_report(self):
        state = {
            "grounding_grade": GraderVerdict(
                passed=False, failing_section_ids=["intro"]
            ),
            "revise_iteration": 5,
            "max_revise_iterations": 2,
        }
        assert route_after_grounding_grader(state) == "assemble_report"

    def test_cap_of_one_exits_after_first_revise(self):
        """With max=1, after one revise cycle (iter=1 >= max=1) -> assemble_report."""
        state = {
            "grounding_grade": GraderVerdict(
                passed=False, failing_section_ids=["body"]
            ),
            "revise_iteration": 1,
            "max_revise_iterations": 1,
        }
        assert route_after_grounding_grader(state) == "assemble_report"

    # --- Default cap behavior ---

    def test_default_max_revise_is_two(self):
        """When max_revise_iterations is absent, default is 2."""
        failing_grade = GraderVerdict(passed=False, failing_section_ids=["body"])
        # iter=1 < default max=2 -> revise_section
        state = {"grounding_grade": failing_grade, "revise_iteration": 1}
        assert route_after_grounding_grader(state) == "revise_section"

        # iter=2 >= default max=2 -> assemble_report
        state["revise_iteration"] = 2
        assert route_after_grounding_grader(state) == "assemble_report"
