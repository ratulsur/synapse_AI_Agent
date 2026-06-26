"""Route handlers and Pydantic request/response DTOs for the Synapse API.

DTOs are explicit, clean, and versioned here -- they are the contract between
the backend graph and the frontend UI.  Every field is documented so the
frontend can consume this file as a reference.

Endpoint summary
----------------
GET  /healthz                       -- liveness probe
POST /runs                          -- start a run; pauses at HITL interrupt
POST /runs/{thread_id}/resume       -- resume with approve / edit / reject
GET  /runs/{thread_id}              -- current status + result from checkpointer
GET  /runs/{thread_id}/stream       -- SSE stream of checkpoint history events

HITL interrupt / resume contract
---------------------------------
``POST /runs`` invokes the graph until the ``human_in_the_loop`` node fires
``interrupt()``.  The response carries ``status="awaiting_plan_approval"`` and
the generated ``plan`` dict.

``POST /runs/{thread_id}/resume`` accepts one of three actions:

  action="approve"  ->  Command(resume={"approved": True})
                        Graph continues to query_router and runs to completion.
                        Response: status="completed", report + final_answer populated.

  action="edit"     ->  Command(resume={"approved": False, "plan": <edited_plan>})
                        Graph loops back through scope_plan (re-plans with edits)
                        then hits the HITL interrupt again.
                        Response: status="awaiting_plan_approval", updated plan.

  action="reject"   ->  Command(resume={"approved": False})
                        Graph loops back through scope_plan (re-plans from scratch)
                        then hits the HITL interrupt again.
                        Response: status="awaiting_plan_approval", updated plan.

Owner: backend-developer (DTO shape co-owned with frontend-ui-developer)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log


# ---------------------------------------------------------------------------
# Request / Response DTOs
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Body for ``POST /runs``.

    Only ``query`` is required.  The iteration-cap overrides are optional and
    useful for callers that want tighter or looser loops (e.g., tests or power
    users).
    """

    query: str = Field(description="The research question or topic to investigate.")
    max_retrieval_iterations: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Override for the retrieval-evidence loop cap "
            "(default read from config/configuration.yaml agent.max_retrieval_iterations)."
        ),
    )
    max_revise_iterations: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Override for the grounding-revise loop cap "
            "(default read from config/configuration.yaml agent.max_revise_iterations)."
        ),
    )


class SectionSpecDTO(BaseModel):
    """DTO for a single section spec inside a ReportPlan."""

    id: str = Field(description="Stable identifier for the section (e.g. 'intro', 'body').")
    heading: str = Field(description="Display heading rendered in the report.")
    intent: str = Field(default="", description="High-level instruction for the writer.")
    order: int = Field(default=0, description="Ordinal position (ascending, 0-based).")


class PlanDTO(BaseModel):
    """DTO for a ReportPlan -- audience / length / tone / ordered sections."""

    audience: str = Field(default="general", description="Intended audience for the report.")
    length: str = Field(
        default="medium",
        description="Approximate length: 'short' | 'medium' | 'long' or a word target.",
    )
    tone: str = Field(
        default="neutral",
        description="Writing tone: 'formal' | 'conversational' | 'neutral'.",
    )
    sections: list[SectionSpecDTO] = Field(
        default_factory=list,
        description="Ordered section specifications (sorted by SectionSpec.order).",
    )


class RunResponse(BaseModel):
    """Response from ``POST /runs``.

    On a normal first invocation the graph pauses at the HITL interrupt and
    ``status`` is ``"awaiting_plan_approval"``.  ``plan`` carries the generated
    ReportPlan dict and ``interrupt_payload`` carries the full interrupt value
    (query + plan + instructions).
    """

    thread_id: str = Field(description="Stable ID to address subsequent resume / status calls.")
    status: Literal["awaiting_plan_approval", "completed", "error"] = Field(
        description="Current run status."
    )
    plan: Optional[dict] = Field(
        default=None,
        description="ReportPlan dict generated by scope_plan; present when status='awaiting_plan_approval'.",
    )
    interrupt_payload: Optional[dict] = Field(
        default=None,
        description="Full interrupt event payload (event, query, plan, instructions).",
    )


class ResumeRequest(BaseModel):
    """Body for ``POST /runs/{thread_id}/resume``.

    The ``action`` field drives the LangGraph ``Command(resume=...)`` value:

    - ``"approve"``  -- plan is accepted; graph proceeds to retrieval + writing.
    - ``"edit"``     -- ``edited_plan`` is applied; graph loops through scope_plan again.
    - ``"reject"``   -- plan is discarded; graph re-runs scope_plan from scratch.
    """

    action: Literal["approve", "edit", "reject"] = Field(
        description="Human decision: 'approve' | 'edit' | 'reject'."
    )
    edited_plan: Optional[dict] = Field(
        default=None,
        description=(
            "Edited ReportPlan dict; required when action='edit'.  "
            "Must match the PlanDTO shape (audience, length, tone, sections[])."
        ),
    )


class SectionDTO(BaseModel):
    """DTO for a drafted Section (one per spec_id)."""

    spec_id: str = Field(description="FK to SectionSpec.id.")
    heading: str = Field(description="Display heading for this section.")
    content: str = Field(default="", description="Drafted prose.")
    cited_source_ids: list[str] = Field(
        default_factory=list,
        description="Source.id values this section cites.",
    )
    status: str = Field(
        default="pending",
        description="Lifecycle: pending | drafted | grounded | revising.",
    )
    grounded: bool = Field(default=False, description="True when Grounding Grader has cleared this section.")
    revise_count: int = Field(default=0, description="Number of revise-section cycles applied.")


class SourceDTO(BaseModel):
    """DTO for a retrieved evidence Source."""

    id: str = Field(description="Stable content hash for dedup and citation.")
    title: str = Field(description="Document / page title.")
    author: Optional[str] = Field(default=None, description="Primary author(s).")
    url: str = Field(description="Canonical URL of the source.")
    domain: str = Field(
        description="Retrieval domain label (Techno / Education / Travel / Art / Mgmt / GENERIC)."
    )
    content: str = Field(default="", description="Extracted text / snippet used for grounding.")
    score: float = Field(default=0.0, description="Relevance score from the retriever (0..1).")
    tool: Optional[str] = Field(
        default=None,
        description="Tool that produced this source (web / wiki / arxiv / api / mcp).",
    )


class ResumeResponse(BaseModel):
    """Response from ``POST /runs/{thread_id}/resume``.

    When ``action="approve"``:
      status="completed", report and final_answer are populated,
      sections and sources are present if the graph produced them.

    When ``action="edit"`` or ``action="reject"``:
      status="awaiting_plan_approval", plan carries the updated ReportPlan.
    """

    thread_id: str = Field(description="Same thread_id from the original run.")
    status: Literal["awaiting_plan_approval", "completed", "error"] = Field(
        description="Current run status."
    )
    report: Optional[str] = Field(
        default=None,
        description="Assembled report text; present when status='completed'.",
    )
    final_answer: Optional[str] = Field(
        default=None,
        description=(
            "JSON-serialised terminal payload: {query, report, metadata}; "
            "present when status='completed'."
        ),
    )
    sections: Optional[list[SectionDTO]] = Field(
        default=None,
        description="Drafted sections; present when status='completed'.",
    )
    low_confidence: Optional[bool] = Field(
        default=None,
        description="True when the source grader exited at its cap without passing.",
    )
    sources: Optional[list[SourceDTO]] = Field(
        default=None,
        description="Retrieved evidence sources; present when status='completed'.",
    )
    plan: Optional[dict] = Field(
        default=None,
        description="ReportPlan dict; present when status='awaiting_plan_approval' (updated plan).",
    )
    interrupt_payload: Optional[dict] = Field(
        default=None,
        description="Full interrupt payload; present when status='awaiting_plan_approval'.",
    )


class StatusResponse(BaseModel):
    """Response from ``GET /runs/{thread_id}``.

    Reads the checkpointer's most-recent snapshot for the given thread.
    """

    thread_id: str
    status: Literal["awaiting_plan_approval", "completed", "error", "unknown"] = Field(
        description="Inferred from the checkpoint: awaiting_plan_approval | completed | unknown."
    )
    plan: Optional[dict] = Field(default=None, description="ReportPlan dict if available.")
    report: Optional[str] = Field(default=None, description="Assembled report text if completed.")
    final_answer: Optional[str] = Field(default=None, description="Terminal payload if completed.")
    sections: Optional[list[SectionDTO]] = Field(default=None)
    low_confidence: Optional[bool] = Field(default=None)
    sources: Optional[list[SourceDTO]] = Field(default=None)
    next_nodes: list[str] = Field(
        default_factory=list,
        description="Nodes the graph would execute next (from snapshot.next).",
    )


class HealthResponse(BaseModel):
    """Response from ``GET /healthz``."""

    status: str = "ok"
    service: str = "synapse-ai-agent"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_graph(request: Request):
    """Retrieve the compiled graph from app state; raise 503 if not ready."""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised; service is starting up.")
    return graph


def _make_thread_config(thread_id: str) -> dict:
    """Produce the LangGraph ``config`` dict that addresses a specific checkpoint."""
    return {"configurable": {"thread_id": thread_id}}


def _infer_status_from_invoke_result(result: dict) -> Literal["awaiting_plan_approval", "completed"]:
    """Infer run status from the raw dict returned by ``graph.invoke()``."""
    if "__interrupt__" in result:
        return "awaiting_plan_approval"
    return "completed"


def _infer_status_from_snapshot(
    snapshot,
) -> Literal["awaiting_plan_approval", "completed", "unknown"]:
    """Infer run status from a LangGraph ``StateSnapshot``.

    Checks (in priority order):
    1. ``snapshot.tasks`` -- any task with non-empty ``.interrupts`` -> awaiting.
    2. ``snapshot.values.get("final_answer")`` -> completed.
    3. Non-empty ``snapshot.next`` -> awaiting (paused before some node).
    4. Fallthrough -> unknown (thread may not have run yet or state is empty).
    """
    if snapshot is None:
        return "unknown"

    values: dict = snapshot.values or {}

    # Priority 1: explicit interrupt tasks (most reliable for HITL detection)
    try:
        if snapshot.tasks:
            for task in snapshot.tasks:
                if getattr(task, "interrupts", None):
                    return "awaiting_plan_approval"
    except Exception:
        pass

    # Priority 2: completed run
    if values.get("final_answer"):
        return "completed"

    # Priority 3: graph paused (pending next node)
    try:
        if snapshot.next:
            return "awaiting_plan_approval"
    except Exception:
        pass

    if not values:
        return "unknown"

    return "unknown"


def _sections_dto(state_values: dict) -> Optional[list[SectionDTO]]:
    """Convert raw ``Section`` objects from state into ``SectionDTO`` list."""
    raw = state_values.get("sections")
    if not raw:
        return None
    result: list[SectionDTO] = []
    for s in raw:
        try:
            result.append(
                SectionDTO(
                    spec_id=s.spec_id,
                    heading=s.heading,
                    content=s.content,
                    cited_source_ids=list(s.cited_source_ids),
                    status=s.status,
                    grounded=s.grounded,
                    revise_count=s.revise_count,
                )
            )
        except Exception as exc:
            log.warning("api: failed to convert section to DTO", error=str(exc))
    return result or None


def _sources_dto(state_values: dict) -> Optional[list[SourceDTO]]:
    """Convert raw ``Source`` objects from state into ``SourceDTO`` list."""
    raw = state_values.get("sources")
    if not raw:
        return None
    result: list[SourceDTO] = []
    for s in raw:
        try:
            result.append(
                SourceDTO(
                    id=s.id,
                    title=s.title,
                    author=s.author,
                    url=s.url,
                    domain=s.domain,
                    content=s.content,
                    score=s.score,
                    tool=s.tool,
                )
            )
        except Exception as exc:
            log.warning("api: failed to convert source to DTO", error=str(exc))
    return result or None


def _plan_dict(state_values: dict) -> Optional[dict]:
    """Serialise the ``ReportPlan`` from state into a plain dict."""
    plan_obj = state_values.get("plan")
    if plan_obj is None:
        return None
    try:
        return plan_obj.model_dump()
    except Exception:
        return None


def _safe_json(value: Any) -> Any:
    """Return a JSON-serialisable representation of ``value``."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["meta"])
async def healthz() -> HealthResponse:
    """Liveness probe -- always returns 200 if the process is up."""
    return HealthResponse(status="ok", service="synapse-ai-agent")


@router.post("/runs", response_model=RunResponse, tags=["runs"])
async def start_run(body: RunRequest, request: Request) -> RunResponse:
    """Start a new research run.

    Invokes the graph from the initial state until the ``human_in_the_loop``
    node fires ``interrupt()``.  Returns ``thread_id`` + the generated plan so
    the frontend can display it for human review.

    The returned ``thread_id`` must be supplied to subsequent ``/resume`` and
    ``/stream`` calls.
    """
    graph = _get_graph(request)
    thread_id = str(uuid.uuid4())
    cfg = _make_thread_config(thread_id)

    initial_state: dict[str, Any] = {"query": body.query}
    if body.max_retrieval_iterations is not None:
        initial_state["max_retrieval_iterations"] = body.max_retrieval_iterations
    if body.max_revise_iterations is not None:
        initial_state["max_revise_iterations"] = body.max_revise_iterations

    try:
        log.info("api: starting run", thread_id=thread_id, query=body.query[:80])
        result = graph.invoke(initial_state, cfg)
    except ResearchAnalystException:
        raise
    except Exception as exc:
        msg = f"Graph invocation failed for thread_id={thread_id}"
        log.error(msg, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"error": msg, "detail": str(exc)},
        ) from exc

    status = _infer_status_from_invoke_result(result)

    if status == "awaiting_plan_approval":
        interrupts = result.get("__interrupt__", [])
        interrupt_payload: dict = interrupts[0].value if interrupts else {}
        plan = interrupt_payload.get("plan")
        log.info("api: run paused at HITL", thread_id=thread_id)
        return RunResponse(
            thread_id=thread_id,
            status="awaiting_plan_approval",
            plan=plan,
            interrupt_payload=interrupt_payload,
        )

    # Graph ran to completion without a HITL interrupt (unusual but handled)
    log.info("api: run completed without HITL interrupt", thread_id=thread_id)
    return RunResponse(
        thread_id=thread_id,
        status="completed",
        plan=_plan_dict(result),
    )


@router.post(
    "/runs/{thread_id}/resume",
    response_model=ResumeResponse,
    tags=["runs"],
)
async def resume_run(
    thread_id: str,
    body: ResumeRequest,
    request: Request,
) -> ResumeResponse:
    """Resume a paused run with a human decision.

    Maps the ``action`` field to a ``langgraph.types.Command(resume=...)``:

    - ``"approve"``  -> ``{"approved": True}``
      Graph proceeds through retrieval, writing, and grounding to completion.

    - ``"edit"``     -> ``{"approved": False, "plan": edited_plan}``
      Graph loops back through ``scope_plan`` (re-plans using edits as input)
      then pauses at ``human_in_the_loop`` again.

    - ``"reject"``   -> ``{"approved": False}``
      Graph loops back through ``scope_plan`` (re-plans from scratch)
      then pauses at ``human_in_the_loop`` again.
    """
    graph = _get_graph(request)
    cfg = _make_thread_config(thread_id)

    # Build the resume value based on the action
    if body.action == "approve":
        resume_value: dict = {"approved": True}
    elif body.action == "edit":
        if body.edited_plan is None:
            raise HTTPException(
                status_code=422,
                detail="edited_plan is required when action='edit'.",
            )
        resume_value = {"approved": False, "plan": body.edited_plan}
    else:  # reject
        resume_value = {"approved": False}

    try:
        log.info("api: resuming run", thread_id=thread_id, action=body.action)
        result = graph.invoke(Command(resume=resume_value), cfg)
    except ResearchAnalystException:
        raise
    except Exception as exc:
        msg = f"Graph resume failed for thread_id={thread_id}"
        log.error(msg, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"error": msg, "detail": str(exc)},
        ) from exc

    status = _infer_status_from_invoke_result(result)

    if status == "awaiting_plan_approval":
        # Graph looped back to HITL (edit or reject path)
        interrupts = result.get("__interrupt__", [])
        interrupt_payload = interrupts[0].value if interrupts else {}
        plan = interrupt_payload.get("plan")
        log.info("api: run paused again at HITL", thread_id=thread_id, action=body.action)
        return ResumeResponse(
            thread_id=thread_id,
            status="awaiting_plan_approval",
            plan=plan,
            interrupt_payload=interrupt_payload,
        )

    # Completed
    log.info("api: run completed", thread_id=thread_id)
    return ResumeResponse(
        thread_id=thread_id,
        status="completed",
        report=result.get("report"),
        final_answer=result.get("final_answer"),
        sections=_sections_dto(result),
        low_confidence=result.get("low_confidence"),
        sources=_sources_dto(result),
        plan=_plan_dict(result),
    )


@router.get(
    "/runs/{thread_id}",
    response_model=StatusResponse,
    tags=["runs"],
)
async def get_run_status(thread_id: str, request: Request) -> StatusResponse:
    """Fetch the current status and result of a run from the checkpointer.

    Uses ``graph.get_state(config)`` to read the latest checkpoint for the
    given ``thread_id`` without advancing the graph.  Returns the inferred
    status, the plan (if generated), and the report / final_answer / sections
    / sources if the run has completed.
    """
    graph = _get_graph(request)
    cfg = _make_thread_config(thread_id)

    try:
        snapshot = graph.get_state(cfg)
    except Exception as exc:
        log.error(
            "api: get_state failed",
            thread_id=thread_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=404,
            detail={"error": "Thread not found or checkpointer error", "thread_id": thread_id},
        ) from exc

    if snapshot is None or not snapshot.values:
        return StatusResponse(thread_id=thread_id, status="unknown")

    values = snapshot.values
    status = _infer_status_from_snapshot(snapshot)

    next_nodes: list[str] = []
    try:
        next_nodes = list(snapshot.next) if snapshot.next else []
    except Exception:
        pass

    return StatusResponse(
        thread_id=thread_id,
        status=status,
        plan=_plan_dict(values),
        report=values.get("report"),
        final_answer=values.get("final_answer"),
        sections=_sections_dto(values),
        low_confidence=values.get("low_confidence"),
        sources=_sources_dto(values),
        next_nodes=next_nodes,
    )


@router.get("/runs/{thread_id}/stream", tags=["runs"])
async def stream_run(thread_id: str, request: Request) -> StreamingResponse:
    """Stream checkpoint-history events as server-sent events (SSE).

    Emits one ``checkpoint`` event per saved graph checkpoint for the given
    ``thread_id`` (most-recent first), then a final ``done`` event.

    Each event is a JSON object with at minimum:
      ``{"event": "checkpoint", "thread_id": "...", "status": "...", "step": N, "next": [...]}``

    Clients should parse ``data:`` lines, skip blank lines, and parse the JSON.
    The ``done`` event signals the end of the stream.

    Errors are surfaced as an ``error`` event so the client can react without
    losing the connection silently.
    """
    graph = _get_graph(request)
    cfg = _make_thread_config(thread_id)

    def _event_generator():
        try:
            history_count = 0
            for snapshot in graph.get_state_history(cfg):
                values: dict = snapshot.values or {}
                snap_status = _infer_status_from_snapshot(snapshot)

                # Extract the node(s) that wrote this checkpoint from metadata
                source_node: Optional[str] = None
                try:
                    meta = snapshot.metadata or {}
                    writes = meta.get("writes") or {}
                    nodes_written = list(writes.keys()) if writes else []
                    source_node = nodes_written[0] if nodes_written else meta.get("source")
                except Exception:
                    pass

                next_nodes: list[str] = []
                try:
                    next_nodes = list(snapshot.next) if snapshot.next else []
                except Exception:
                    pass

                step = history_count
                try:
                    step = (snapshot.metadata or {}).get("step", history_count)
                except Exception:
                    pass

                event_data = {
                    "event": "checkpoint",
                    "thread_id": thread_id,
                    "status": snap_status,
                    "step": step,
                    "node": source_node,
                    "next": next_nodes,
                    "has_report": bool(values.get("report")),
                    "has_final_answer": bool(values.get("final_answer")),
                    "low_confidence": values.get("low_confidence"),
                }
                yield f"data: {json.dumps(event_data)}\n\n"
                history_count += 1

                if history_count >= 100:  # safety cap
                    break

            if history_count == 0:
                # Thread not found or no checkpoints -- emit a not-found event
                yield f"data: {json.dumps({'event': 'not_found', 'thread_id': thread_id})}\n\n"

            yield f"data: {json.dumps({'event': 'done', 'thread_id': thread_id, 'total_checkpoints': history_count})}\n\n"

        except Exception as exc:
            log.error("api: stream error", thread_id=thread_id, error=str(exc))
            error_event = {
                "event": "error",
                "thread_id": thread_id,
                "error": str(exc),
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
