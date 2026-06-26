"""Integration smoke tests for the FastAPI API layer.

Strategy
--------
All agent / LLM / tool seams are monkeypatched to raise ``NotImplementedError``
so every graph node falls through to its deterministic stub -- exactly the same
technique used in ``test_graph_flow.py``.  No network calls, no API keys.

The ``TestClient`` enters the app lifespan (which calls ``build_graph()``), then
drives the full HTTP contract.

Tests covered
-------------
1.  ``GET /healthz``                       -- 200, body {"status": "ok"}
2.  ``POST /runs``                         -- 200, status=awaiting_plan_approval, plan present
3.  ``POST /runs/{thread_id}/resume``
      action="approve"                    -- 200, status=completed, report + final_answer
4.  ``POST /runs/{thread_id}/resume``
      action="reject"                     -- 200, status=awaiting_plan_approval (re-interrupt)
5.  ``POST /runs/{thread_id}/resume``
      action="edit" (with edited_plan)    -- 200, status=awaiting_plan_approval (loops)
6.  ``POST /runs/{thread_id}/resume``
      action="edit" (missing edited_plan) -- 422
7.  ``GET /runs/{thread_id}``             -- 200, status present
8.  ``GET /runs/{thread_id}/stream``      -- 200, SSE text/event-stream, "done" event present
9.  Full flow: start -> approve -> completed assertions (report, final_answer, sections)

Owner: Ratul Sur
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Pre-import all agent modules so monkeypatching their module attributes works.
# (Nodes do lazy local imports; if the module is already in sys.modules the
# monkeypatched attribute is picked up at call time.)
# ---------------------------------------------------------------------------

import agents.analyst
import agents.graders.grounding_grader as _gg_mod
import agents.graders.source_grader as _sg_mod
import agents.planner
import agents.react_agent
import agents.reviser
import agents.router_agent
import agents.writers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_ni(*args, **kwargs):
    raise NotImplementedError("stubbed out -- node will use its fallback")


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


def _patch_all_agents(monkeypatch) -> None:
    for mod, fn in _AGENT_PATCHES:
        monkeypatch.setattr(mod, fn, _raise_ni)
    monkeypatch.setattr(_sg_mod, "run_source_grader", _raise_ni)
    monkeypatch.setattr(_gg_mod, "run_grounding_grader", _raise_ni)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    """TestClient with all agent seams stubbed -- no LLM calls, no network."""
    _patch_all_agents(monkeypatch)

    from api.app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Health check
# ---------------------------------------------------------------------------


class TestHealth:
    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_body(self, client):
        resp = client.get("/healthz")
        body = resp.json()
        assert body["status"] == "ok"
        assert "service" in body


# ---------------------------------------------------------------------------
# 2. POST /runs -- start a run, expect HITL interrupt
# ---------------------------------------------------------------------------


class TestStartRun:
    @pytest.mark.timeout(30)
    def test_post_runs_returns_200(self, client):
        resp = client.post("/runs", json={"query": "What is machine learning?"})
        assert resp.status_code == 200

    @pytest.mark.timeout(30)
    def test_post_runs_status_awaiting(self, client):
        resp = client.post("/runs", json={"query": "Test query"})
        body = resp.json()
        assert body["status"] == "awaiting_plan_approval", (
            f"Expected 'awaiting_plan_approval', got: {body.get('status')!r}\nBody: {body}"
        )

    @pytest.mark.timeout(30)
    def test_post_runs_returns_thread_id(self, client):
        resp = client.post("/runs", json={"query": "Test query"})
        body = resp.json()
        assert "thread_id" in body
        assert body["thread_id"]  # non-empty string

    @pytest.mark.timeout(30)
    def test_post_runs_returns_plan(self, client):
        resp = client.post("/runs", json={"query": "Test query about AI"})
        body = resp.json()
        # plan may be None only if scope_plan hasn't run (stub produces a plan always)
        assert "plan" in body, "Response must have 'plan' key"

    @pytest.mark.timeout(30)
    def test_post_runs_returns_interrupt_payload(self, client):
        resp = client.post("/runs", json={"query": "Topic"})
        body = resp.json()
        assert "interrupt_payload" in body
        payload = body["interrupt_payload"]
        if payload:  # may be None for some stubs, but event key must be plan_review
            assert payload.get("event") == "plan_review"

    @pytest.mark.timeout(30)
    def test_post_runs_with_iteration_overrides(self, client):
        resp = client.post(
            "/runs",
            json={
                "query": "Test with overrides",
                "max_retrieval_iterations": 1,
                "max_revise_iterations": 1,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_plan_approval"

    def test_post_runs_missing_query_422(self, client):
        resp = client.post("/runs", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 3. POST /runs/{thread_id}/resume -- approve -> completed
# ---------------------------------------------------------------------------


class TestResumeApprove:
    @pytest.mark.timeout(60)
    def test_approve_returns_200(self, client):
        tid = client.post("/runs", json={"query": "Topic"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        assert resp.status_code == 200

    @pytest.mark.timeout(60)
    def test_approve_status_completed(self, client):
        tid = client.post("/runs", json={"query": "AI in medicine"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        assert body["status"] == "completed", (
            f"Expected 'completed', got: {body.get('status')!r}\nBody: {body}"
        )

    @pytest.mark.timeout(60)
    def test_approve_has_final_answer(self, client):
        tid = client.post("/runs", json={"query": "Renewable energy"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        assert body.get("final_answer"), "final_answer must be non-empty on completion"

    @pytest.mark.timeout(60)
    def test_approve_final_answer_is_json(self, client):
        tid = client.post("/runs", json={"query": "Test report"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        fa = body.get("final_answer")
        assert fa, "final_answer must be present"
        parsed = json.loads(fa)
        assert "query" in parsed
        assert "report" in parsed
        assert "metadata" in parsed

    @pytest.mark.timeout(60)
    def test_approve_has_report(self, client):
        tid = client.post("/runs", json={"query": "Climate change"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        assert body.get("report"), "report must be non-empty on completion"

    @pytest.mark.timeout(60)
    def test_approve_has_sections(self, client):
        tid = client.post("/runs", json={"query": "Jazz music history"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        sections = body.get("sections") or []
        assert len(sections) > 0, "At least one section should be present after completion"
        for sec in sections:
            assert "spec_id" in sec
            assert "heading" in sec
            assert "content" in sec

    @pytest.mark.timeout(60)
    def test_approve_thread_id_echoed(self, client):
        tid = client.post("/runs", json={"query": "Test"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        assert body["thread_id"] == tid


# ---------------------------------------------------------------------------
# 4. POST /runs/{thread_id}/resume -- reject -> re-interrupt
# ---------------------------------------------------------------------------


class TestResumeReject:
    @pytest.mark.timeout(60)
    def test_reject_returns_awaiting(self, client):
        tid = client.post("/runs", json={"query": "Topic X"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "reject"})
        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "awaiting_plan_approval", (
            f"Expected re-interrupt after reject; got status={body.get('status')!r}"
        )

    @pytest.mark.timeout(60)
    def test_reject_then_approve_completes(self, client):
        tid = client.post("/runs", json={"query": "Topic Y"}).json()["thread_id"]
        client.post(f"/runs/{tid}/resume", json={"action": "reject"})
        resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        body = resp.json()
        assert body["status"] == "completed"
        assert body.get("final_answer")


# ---------------------------------------------------------------------------
# 5. POST /runs/{thread_id}/resume -- edit
# ---------------------------------------------------------------------------


class TestResumeEdit:
    _SAMPLE_PLAN = {
        "audience": "general",
        "length": "short",
        "tone": "formal",
        "sections": [
            {"id": "intro", "heading": "Introduction", "intent": "Introduce the topic.", "order": 0},
            {"id": "body", "heading": "Main Body", "intent": "Cover main points.", "order": 1},
            {"id": "conclusion", "heading": "Conclusion", "intent": "Wrap up.", "order": 2},
        ],
    }

    @pytest.mark.timeout(60)
    def test_edit_with_plan_returns_awaiting(self, client):
        tid = client.post("/runs", json={"query": "Topic Z"}).json()["thread_id"]
        resp = client.post(
            f"/runs/{tid}/resume",
            json={"action": "edit", "edited_plan": self._SAMPLE_PLAN},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_plan_approval"

    @pytest.mark.timeout(30)
    def test_edit_without_plan_422(self, client):
        tid = client.post("/runs", json={"query": "Topic"}).json()["thread_id"]
        resp = client.post(f"/runs/{tid}/resume", json={"action": "edit"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 6. GET /runs/{thread_id} -- status endpoint
# ---------------------------------------------------------------------------


class TestGetRunStatus:
    @pytest.mark.timeout(60)
    def test_get_status_after_start(self, client):
        tid = client.post("/runs", json={"query": "Status check"}).json()["thread_id"]
        resp = client.get(f"/runs/{tid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "thread_id" in body
        assert body["thread_id"] == tid

    @pytest.mark.timeout(60)
    def test_get_status_awaiting_after_start(self, client):
        tid = client.post("/runs", json={"query": "Status query"}).json()["thread_id"]
        resp = client.get(f"/runs/{tid}")
        body = resp.json()
        # After POST /runs the graph is interrupted at HITL; status must reflect that
        assert body["status"] in ("awaiting_plan_approval", "unknown"), (
            f"Unexpected status after start: {body['status']!r}"
        )

    @pytest.mark.timeout(60)
    def test_get_status_completed_after_approve(self, client):
        tid = client.post("/runs", json={"query": "Full run"}).json()["thread_id"]
        client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        resp = client.get(f"/runs/{tid}")
        body = resp.json()
        assert body["status"] == "completed", (
            f"Expected completed after approval; got {body['status']!r}"
        )
        assert body.get("final_answer"), "final_answer must be in status after completion"

    @pytest.mark.timeout(30)
    def test_get_status_nonexistent_thread(self, client):
        fake_tid = str(uuid.uuid4())
        resp = client.get(f"/runs/{fake_tid}")
        # Checkpointer returns empty state for unknown thread; we return 200/unknown or 404
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# 7. GET /runs/{thread_id}/stream -- SSE stream
# ---------------------------------------------------------------------------


class TestStreamRun:
    @pytest.mark.timeout(60)
    def test_stream_returns_200(self, client):
        tid = client.post("/runs", json={"query": "Stream test"}).json()["thread_id"]
        resp = client.get(f"/runs/{tid}/stream")
        assert resp.status_code == 200

    @pytest.mark.timeout(60)
    def test_stream_content_type_sse(self, client):
        tid = client.post("/runs", json={"query": "SSE test"}).json()["thread_id"]
        resp = client.get(f"/runs/{tid}/stream")
        assert "text/event-stream" in resp.headers.get("content-type", "")

    @pytest.mark.timeout(60)
    def test_stream_contains_done_event(self, client):
        tid = client.post("/runs", json={"query": "Stream done test"}).json()["thread_id"]
        resp = client.get(f"/runs/{tid}/stream")
        data_lines = [
            line[6:]  # strip "data: " prefix
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        events = [json.loads(line) for line in data_lines]
        event_names = [e.get("event") for e in events]
        assert "done" in event_names, (
            f"Expected 'done' event in SSE stream; got events: {event_names}"
        )

    @pytest.mark.timeout(60)
    def test_stream_after_complete_has_checkpoint_events(self, client):
        tid = client.post("/runs", json={"query": "Complete stream test"}).json()["thread_id"]
        client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        resp = client.get(f"/runs/{tid}/stream")
        data_lines = [
            line[6:]
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        events = [json.loads(line) for line in data_lines]
        checkpoint_events = [e for e in events if e.get("event") == "checkpoint"]
        assert len(checkpoint_events) > 0, (
            "Expected at least one 'checkpoint' event after a completed run"
        )

    @pytest.mark.timeout(30)
    def test_stream_nonexistent_thread_returns_not_found_event(self, client):
        fake_tid = str(uuid.uuid4())
        resp = client.get(f"/runs/{fake_tid}/stream")
        assert resp.status_code == 200  # SSE always returns 200
        data_lines = [
            line[6:]
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        events = [json.loads(line) for line in data_lines]
        event_names = [e.get("event") for e in events]
        assert "not_found" in event_names or "done" in event_names


# ---------------------------------------------------------------------------
# 8. Full flow integration test
# ---------------------------------------------------------------------------


class TestFullFlow:
    @pytest.mark.timeout(60)
    def test_start_approve_full_contract(self, client):
        """Drive the complete HTTP contract end to end."""
        # --- Start ---
        start_resp = client.post(
            "/runs",
            json={"query": "Impact of AI on education", "max_revise_iterations": 1},
        )
        assert start_resp.status_code == 200
        start_body = start_resp.json()
        assert start_body["status"] == "awaiting_plan_approval"
        tid = start_body["thread_id"]
        assert tid

        # --- Approve ---
        approve_resp = client.post(f"/runs/{tid}/resume", json={"action": "approve"})
        assert approve_resp.status_code == 200
        approve_body = approve_resp.json()
        assert approve_body["status"] == "completed"
        assert approve_body["thread_id"] == tid
        assert approve_body.get("report"), "report must be non-empty"
        assert approve_body.get("final_answer"), "final_answer must be non-empty"
        sections = approve_body.get("sections") or []
        assert len(sections) > 0, "At least one section after completion"
        for sec in sections:
            assert sec.get("content"), f"Section {sec.get('spec_id')!r} has empty content"

        # --- Status check after completion ---
        status_resp = client.get(f"/runs/{tid}")
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["status"] == "completed"
        assert status_body.get("final_answer")

        # --- Health still OK ---
        health_resp = client.get("/healthz")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"
