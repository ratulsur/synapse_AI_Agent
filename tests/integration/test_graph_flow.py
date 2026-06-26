"""Integration seam tests for the full graph flow.

All agent / LLM / tool seams are monkeypatched so tests are:
  - OFFLINE: zero network calls, zero API keys required.
  - FAST: no real LLM invocation.
  - DETERMINISTIC: fixed stub returns; loop caps passed via initial state.

Strategy: monkeypatch every agent function (in its source module) to raise
NotImplementedError so the fall-through stubs inside each graph node activate.
For grader-specific tests, the grader function is patched to return a controlled
GraderVerdict (not raise) so we can steer the loop behavior.

Tests covered:
1. test_hitl_fires_interrupt          - interrupt event fires, payload has plan_review event.
2. test_hitl_approve_runs_to_end      - full end-to-end with approval reaches final_answer.
3. test_hitl_reject_loops_to_scope    - rejection causes another HITL interrupt (scope_plan loop).
4. test_grounding_revise_loop_terminates_at_cap
   - grounding grader always fails; max_revise_iterations=1; graph exits to assemble_report.
5. test_source_grader_loop_terminates_at_cap_sets_low_confidence
   - source grader always fails; max_retrieval_iterations=1; low_confidence=True in output.

Owner: Ratul Sur
"""

from __future__ import annotations

import uuid

import pytest

# Pre-import all agent modules so they are in sys.modules before monkeypatching.
# (The node functions do local 'from agents.xxx import yyy' -- if the module is
# already cached, monkeypatching the module attribute is effective.)
import agents.analyst
import agents.graders.grounding_grader as _gg_mod
import agents.graders.source_grader as _sg_mod
import agents.planner
import agents.react_agent
import agents.reviser
import agents.writers
import agents.router_agent

from schemas.grading import GraderVerdict, MutationAction


# ---------------------------------------------------------------------------
# Helper: patch all agent functions to raise NotImplementedError
# (nodes then activate their built-in fallback stubs)
# ---------------------------------------------------------------------------


def _raise_ni(*args, **kwargs):
    raise NotImplementedError("stubbed out for tests -- node will use its fallback")


_AGENT_PATCHES = [
    (agents.analyst, "run_analyst"),
    (agents.planner, "run_planner"),
    (agents.router_agent, "run_router"),
    (agents.react_agent, "run_react_agent"),
    (agents.writers, "write_intro"),
    (agents.writers, "write_body"),
    (agents.writers, "write_conclusion"),
    (agents.reviser, "run_reviser"),
]


def _patch_all_agents_to_stubs(monkeypatch) -> None:
    """Patch every agent function so node stubs activate (no LLM calls)."""
    for mod, fn in _AGENT_PATCHES:
        monkeypatch.setattr(mod, fn, _raise_ni)
    # Source grader patch: also raise -> stub passes (passes by default)
    monkeypatch.setattr(_sg_mod, "run_source_grader", _raise_ni)
    # Grounding grader patch: also raise -> stub passes (passes by default)
    monkeypatch.setattr(_gg_mod, "run_grounding_grader", _raise_ni)


def _tid() -> str:
    """Unique thread_id per test call to avoid checkpointer state bleed."""
    return f"test-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# 1. HITL interrupt fires
# ---------------------------------------------------------------------------


class TestHITLInterrupt:
    @pytest.mark.timeout(30)
    def test_hitl_fires_interrupt(self, monkeypatch):
        """graph.invoke() pauses at human_in_the_loop and returns __interrupt__."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        state = g.invoke({"query": "What is machine learning?"}, cfg)

        assert "__interrupt__" in state, (
            "Expected graph to pause at human_in_the_loop and return __interrupt__; "
            f"got keys: {list(state.keys())}"
        )

    @pytest.mark.timeout(30)
    def test_hitl_interrupt_payload_has_plan_review_event(self, monkeypatch):
        """The interrupt value contains the plan review payload."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}
        state = g.invoke({"query": "Test query"}, cfg)

        interrupts = state.get("__interrupt__", [])
        assert len(interrupts) > 0

        interrupt_value = interrupts[0].value
        assert interrupt_value.get("event") == "plan_review", (
            f"Interrupt payload missing 'event: plan_review'; got: {interrupt_value}"
        )

    @pytest.mark.timeout(30)
    def test_hitl_interrupt_carries_query(self, monkeypatch):
        """The interrupt payload surfaces the original query for the UI layer."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}
        state = g.invoke({"query": "What is the history of jazz music?"}, cfg)

        interrupt_value = state["__interrupt__"][0].value
        assert interrupt_value.get("query") == "What is the history of jazz music?"

    @pytest.mark.timeout(30)
    def test_hitl_interrupt_carries_plan(self, monkeypatch):
        """Interrupt payload includes the generated plan (or None if not yet produced)."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}
        state = g.invoke({"query": "Test"}, cfg)

        interrupt_value = state["__interrupt__"][0].value
        # 'plan' key must exist (may be None if scope_plan hasn't run yet, but
        # the architecture runs scope_plan before HITL so plan should be populated)
        assert "plan" in interrupt_value


# ---------------------------------------------------------------------------
# 2. Full run: HITL approve -> reaches final_answer
# ---------------------------------------------------------------------------


class TestFullRunApprove:
    @pytest.mark.timeout(60)
    def test_approve_runs_to_final_answer(self, monkeypatch):
        """After HITL interrupt is resumed with approval, graph runs to final_answer."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        tid = _tid()
        cfg = {"configurable": {"thread_id": tid}}

        # Phase 1: run until HITL interrupt
        state1 = g.invoke({"query": "Impact of AI on education"}, cfg)
        assert "__interrupt__" in state1, "Expected HITL interrupt"

        # Phase 2: resume with approval
        state2 = g.invoke(Command(resume={"approved": True}), cfg)

        assert "final_answer" in state2, (
            f"Expected final_answer in state after approval; got keys: {list(state2.keys())}"
        )
        assert state2["final_answer"], "final_answer must be non-empty"

    @pytest.mark.timeout(60)
    def test_final_answer_contains_report_fields(self, monkeypatch):
        """final_answer is a JSON string with 'query', 'report', 'metadata' keys."""
        import json

        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        state = g.invoke({"query": "Test query for report"}, cfg)
        state = g.invoke(Command(resume={"approved": True}), cfg)

        payload = json.loads(state["final_answer"])
        assert "query" in payload
        assert "report" in payload
        assert "metadata" in payload

    @pytest.mark.timeout(60)
    def test_sections_present_after_full_run(self, monkeypatch):
        """After approval and completion, sections are drafted (non-empty stubs)."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        g.invoke({"query": "test"}, cfg)
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        sections = final_state.get("sections", [])
        assert len(sections) > 0, "Expected at least one drafted section"
        for sec in sections:
            # Each section should have content from the stub writers
            assert sec.content, f"Section {sec.spec_id!r} has empty content"

    @pytest.mark.timeout(60)
    def test_report_non_empty_after_full_run(self, monkeypatch):
        """The assembled report string must be non-empty."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        g.invoke({"query": "renewable energy"}, cfg)
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        assert final_state.get("report"), "assembled report must not be empty"


# ---------------------------------------------------------------------------
# 3. HITL reject -> loops to scope_plan (another interrupt fires)
# ---------------------------------------------------------------------------


class TestHITLReject:
    @pytest.mark.timeout(60)
    def test_reject_causes_another_interrupt(self, monkeypatch):
        """Rejecting the plan triggers scope_plan again and fires a new interrupt."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        # First interrupt
        state1 = g.invoke({"query": "Topic X"}, cfg)
        assert "__interrupt__" in state1

        # Resume with rejection
        state2 = g.invoke(Command(resume={"approved": False}), cfg)

        # Graph should loop back to scope_plan -> human_in_the_loop -> interrupt again
        assert "__interrupt__" in state2, (
            "Expected another interrupt after plan rejection (scope_plan loop); "
            f"got keys: {list(state2.keys())}"
        )

    @pytest.mark.timeout(60)
    def test_reject_then_approve_reaches_final_answer(self, monkeypatch):
        """Reject first, then approve; graph still reaches final_answer."""
        _patch_all_agents_to_stubs(monkeypatch)
        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        # Run -> interrupt
        g.invoke({"query": "Topic Y"}, cfg)
        # Reject -> loop
        g.invoke(Command(resume={"approved": False}), cfg)
        # Approve -> final
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        assert "final_answer" in final_state


# ---------------------------------------------------------------------------
# 4. Grounding revise loop terminates at cap
# ---------------------------------------------------------------------------


class TestGroundingReviseLoopCap:
    @pytest.mark.timeout(60)
    def test_revise_loop_terminates_at_cap(self, monkeypatch):
        """With max_revise_iterations=1 and always-failing grounding, loop stops at cap.

        Expected trace:
          ...-> section_drafting -> grounding_grader (FAIL, iter=0 < max=1 -> revise)
          -> revise_section (iter becomes 1) -> grounding_grader (FAIL, iter=1 >= max=1)
          -> assemble_report -> final_answer
        """
        # Patch all agent stubs
        for mod, fn in _AGENT_PATCHES:
            monkeypatch.setattr(mod, fn, _raise_ni)
        monkeypatch.setattr(_sg_mod, "run_source_grader", _raise_ni)

        # Grounding grader always fails with body section flagged
        failing_verdict = GraderVerdict(
            passed=False, score=0.2, rationale="test fail",
            failing_section_ids=["body"]
        )
        monkeypatch.setattr(_gg_mod, "run_grounding_grader", lambda state: failing_verdict)

        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        # Use max_revise_iterations=1 via initial state
        g.invoke({"query": "test revise cap", "max_revise_iterations": 1}, cfg)
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        # Must reach final_answer (not stuck in an infinite revise loop)
        assert "final_answer" in final_state, (
            "Graph did not reach final_answer; cap termination may be broken"
        )
        # At least one revise cycle must have occurred
        assert final_state.get("revise_iteration", 0) >= 1, (
            "revise_iteration should be >= 1 after at least one revise cycle"
        )

    @pytest.mark.timeout(60)
    def test_revise_loop_at_cap_does_not_set_low_confidence(self, monkeypatch):
        """Low confidence is a source-grader flag, NOT the grounding-grader flag."""
        for mod, fn in _AGENT_PATCHES:
            monkeypatch.setattr(mod, fn, _raise_ni)
        monkeypatch.setattr(_sg_mod, "run_source_grader", _raise_ni)

        failing_verdict = GraderVerdict(
            passed=False, score=0.2, failing_section_ids=["body"]
        )
        monkeypatch.setattr(_gg_mod, "run_grounding_grader", lambda state: failing_verdict)

        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        g.invoke({"query": "test", "max_revise_iterations": 1}, cfg)
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        # low_confidence is not set by grounding grader termination
        assert not final_state.get("low_confidence", False)


# ---------------------------------------------------------------------------
# 5. Source grader loop terminates at cap -> low_confidence set
# ---------------------------------------------------------------------------


class TestSourceGraderLoopCap:
    @pytest.mark.timeout(60)
    def test_source_grader_at_cap_sets_low_confidence(self, monkeypatch):
        """With max_retrieval_iterations=1 and always-failing source grader,
        low_confidence=True is set and graph still produces a final_answer.

        Expected trace:
          -> tool_calls -> normalize -> dedup -> save_checkpoint
          -> source_grader (FAIL, iter=1 >= max=1 -> low_confidence=True, END)
          -> write -> section_drafting -> grounding_grader (pass, stub)
          -> assemble_report -> final_answer
        """
        for mod, fn in _AGENT_PATCHES:
            monkeypatch.setattr(mod, fn, _raise_ni)

        # Source grader always fails
        failing_source_verdict = GraderVerdict(
            passed=False, score=0.1, rationale="not enough sources",
            mutation_action=MutationAction.WIDEN,
        )
        monkeypatch.setattr(_sg_mod, "run_source_grader", lambda state: failing_source_verdict)
        # Grounding grader passes (default stub behavior when raised)
        monkeypatch.setattr(_gg_mod, "run_grounding_grader", _raise_ni)

        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        # max_retrieval_iterations=1: one failing iteration -> exit with low_confidence
        g.invoke({"query": "test source cap", "max_retrieval_iterations": 1}, cfg)
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        # Must reach final_answer
        assert "final_answer" in final_state, (
            "Graph did not reach final_answer after source grader cap"
        )
        # low_confidence must be set
        assert final_state.get("low_confidence", False) is True, (
            "low_confidence should be True when source grader exits at cap without passing"
        )

    @pytest.mark.timeout(60)
    def test_source_grader_at_cap_report_flagged(self, monkeypatch):
        """When low_confidence=True, the assembled report contains the low-confidence note."""
        for mod, fn in _AGENT_PATCHES:
            monkeypatch.setattr(mod, fn, _raise_ni)

        failing_verdict = GraderVerdict(
            passed=False, score=0.1, mutation_action=MutationAction.WIDEN
        )
        monkeypatch.setattr(_sg_mod, "run_source_grader", lambda state: failing_verdict)
        monkeypatch.setattr(_gg_mod, "run_grounding_grader", _raise_ni)

        from graph.builder import build_graph
        from langgraph.types import Command

        g = build_graph()
        cfg = {"configurable": {"thread_id": _tid()}}

        g.invoke({"query": "test flag", "max_retrieval_iterations": 1}, cfg)
        final_state = g.invoke(Command(resume={"approved": True}), cfg)

        report = final_state.get("report", "")
        assert "low-confidence" in report.lower() or "low_confidence" in report.lower(), (
            "Expected low-confidence disclaimer in report when source grader failed at cap"
        )
