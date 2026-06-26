"""Subgraph: Retrieval & Evidence Loop.

Internal topology (from research_agent_v2 diagram):
    tool_calls -> normalize -> deduplication -> save_checkpoint -> source_grader
    source_grader --pass--> END (exit to parent: write)
    source_grader --fail + iteration < max--> tool_calls   (apply mutation_action)
    source_grader --fail + iteration >= max--> END (low_confidence already set)

Each node delegates to its respective owned layer:
    tool_calls       -> agents.react_agent (ReAct over active domains)
    normalize        -> tools.processing.normalize (raw hits -> Source)
    deduplication    -> tools.processing.dedup (url/content-hash dedup)
    save_checkpoint  -> persistence.source_store (typed Source[] -> SQLite)
    source_grader    -> agents.graders.source_grader (LLM judge -> GraderVerdict)

ToolMessage -> normalize wiring
--------------------------------
After tool_calls runs, the ReAct agent appends ``ToolMessage`` objects to
``state['messages']``.  Each ToolMessage carries the JSON string output of a
single tool invocation.  ``_normalize`` parses every ToolMessage in the
current messages list whose content parses as a JSON array, normalises the
hit dicts into ``Source`` objects, and pre-deduplicates against already-
accumulated ``state['sources']`` before returning them to the reducer.

Owner: backend-developer (agent + grader prompts: agent-prompt-engineer)
"""

from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph

from exception.custom_exception import ResearchAnalystException
from graph.routers import route_after_source_grader
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.grading import GraderVerdict, MutationAction
from schemas.source import Source


# ---------------------------------------------------------------------------
# Internal node callables
# ---------------------------------------------------------------------------

def _tool_calls(state: GraphState) -> dict:
    """Run the ReAct tool-use agent over the active domains.

    On re-entry (mutation loop), honours mutation_action to reformulate, widen,
    or reroute.  Appends raw retrieval hits to messages for normalize to read.
    """
    try:
        query: str = state.get("query", "")
        active_domains: list[str] = state.get("active_domains") or ["GENERIC"]
        mutation_action: str | None = state.get("mutation_action")

        log.info(
            "retrieval/tool_calls: invoking ReAct agent",
            query_preview=query[:60],
            domains=active_domains,
            mutation_action=mutation_action,
        )

        try:
            from agents.react_agent import run_react_agent  # type: ignore[import]
            result: dict = run_react_agent(state)
            return result  # expected keys: messages (raw hits appended)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("retrieval/tool_calls: react_agent stub not ready, using empty result")
            return {}

    except Exception as exc:
        msg = "retrieval subgraph tool_calls node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _normalize(state: GraphState) -> dict:
    """Convert raw ToolMessage content into typed ``Source`` objects.

    Parses every ``ToolMessage`` in ``state['messages']`` whose content is a
    JSON array of hit dicts, normalises each hit via
    ``tools.processing.normalize``, pre-deduplicates the result against
    already-accumulated ``state['sources']``, and returns only the truly-new
    sources for the LangGraph reducer to accumulate.
    """
    try:
        log.debug("retrieval/normalize: normalising raw hits")

        try:
            from langchain_core.messages import ToolMessage
            from tools.processing.normalize import normalize  # type: ignore[import]
            from tools.processing.dedup import dedup  # type: ignore[import]

            active_domains: list[str] = state.get("active_domains") or ["GENERIC"]
            domain: str = active_domains[0] if active_domains else "GENERIC"

            # --- Parse ToolMessage JSON payloads into raw hit dicts ---
            messages = state.get("messages") or []
            raw_hits: list[dict] = []
            for msg in messages:
                if not isinstance(msg, ToolMessage):
                    continue
                content = msg.content or ""
                if not content:
                    continue
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        raw_hits.extend(
                            h for h in parsed if isinstance(h, dict)
                        )
                    else:
                        log.debug(
                            "retrieval/normalize: ToolMessage content is not a list, skipping",
                            tool_call_id=getattr(msg, "tool_call_id", "?"),
                        )
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Not JSON (e.g. error strings from stubbed tools), skip.
                    log.debug(
                        "retrieval/normalize: non-JSON ToolMessage content, skipping",
                        preview=content[:60],
                    )

            log.info(
                "retrieval/normalize: parsed raw_hits from ToolMessages",
                raw_hit_count=len(raw_hits),
                message_count=len(messages),
            )

            # --- Normalize raw hits -> Source objects ---
            new_sources: list[Source] = normalize(raw_hits, domain=domain, tool="react")

            # --- Pre-dedup against already-accumulated sources ---
            existing: list[Source] = state.get("sources") or []
            merged = dedup(existing, new_sources)
            existing_ids = {s.id for s in existing}
            truly_new = [s for s in merged if s.id not in existing_ids]

            log.info(
                "retrieval/normalize: returning new sources",
                new_count=len(truly_new),
                existing_count=len(existing),
            )
            return {"sources": truly_new} if truly_new else {}

        except (ImportError, NotImplementedError, AttributeError) as exc:
            log.debug("retrieval/normalize: dependency not ready, returning empty list", error=str(exc))
            return {}

    except Exception as exc:
        msg = "retrieval subgraph normalize node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _deduplication(state: GraphState) -> dict:
    """URL-level sanity check on all accumulated sources.

    The primary id-based deduplication is already performed by both the
    ``add_sources_reducer`` and the pre-dedup step in ``_normalize``.  This
    node performs a secondary URL-level scan across all accumulated sources,
    logs any remaining duplicates for observability, and returns no state
    change (sources are already clean at this point).
    """
    try:
        log.debug("retrieval/deduplication: url-level sanity check")

        try:
            from tools.processing.dedup import dedup  # type: ignore[import]

            all_sources: list[Source] = state.get("sources") or []
            if not all_sources:
                return {}

            # Run dedup over all accumulated sources to find URL-level dupes.
            merged = dedup([], all_sources)
            dropped = len(all_sources) - len(merged)
            if dropped:
                log.warning(
                    "retrieval/deduplication: url-level duplicates detected",
                    total=len(all_sources),
                    unique=len(merged),
                    dropped=dropped,
                )
            else:
                log.debug(
                    "retrieval/deduplication: no url-level duplicates found",
                    total=len(all_sources),
                )

            # We cannot remove from the accumulated state via the reducer;
            # the pre-dedup in _normalize prevents new dupes from entering.
            return {}

        except (ImportError, NotImplementedError, AttributeError):
            log.debug("retrieval/deduplication: dedup not ready, no-op")
            return {}

    except Exception as exc:
        msg = "retrieval subgraph deduplication node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _save_checkpoint(state: GraphState) -> dict:
    """Persist current source list to SQLite via persistence.source_store."""
    try:
        log.debug("retrieval/save_checkpoint: persisting sources")

        try:
            from persistence.source_store import save_sources  # type: ignore[import]
            # thread_id would come from the LangGraph config; use a placeholder here.
            # TODO: accept config: RunnableConfig as second arg to get the real thread_id.
            thread_id: str = "default"
            sources: list[Source] = state.get("sources") or []
            save_sources(thread_id, sources)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("retrieval/save_checkpoint: source_store stub not ready, skipping persist")

        return {}  # no state update; side-effect only

    except Exception as exc:
        msg = "retrieval subgraph save_checkpoint node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _source_grader(state: GraphState) -> dict:
    """LLM-judge: assess whether accumulated sources satisfy the plan.

    Updates:
        source_grade         -- GraderVerdict
        mutation_action      -- str | None  (from verdict on failure)
        retrieval_iteration  -- int  (incremented)
        low_confidence       -- bool  (True when at cap and not passed)
    """
    try:
        retrieval_iteration: int = state.get("retrieval_iteration", 0) + 1
        max_retrieval_iterations: int = state.get("max_retrieval_iterations", 3)
        sources: list[Source] = state.get("sources") or []

        log.info(
            "retrieval/source_grader: grading sources",
            source_count=len(sources),
            iteration=retrieval_iteration,
            max=max_retrieval_iterations,
        )

        try:
            from agents.graders.source_grader import run_source_grader  # type: ignore[import]
            verdict: GraderVerdict = run_source_grader(state)
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("retrieval/source_grader: grader stub not ready, returning passing verdict")
            # Stub: pass so the subgraph can exit.
            verdict = GraderVerdict(
                passed=True,
                score=1.0,
                rationale="Stub: source grader agent not yet implemented.",
                mutation_action=None,
            )

        # Set low_confidence if at cap and still failing.
        low_confidence: bool = (
            not verdict.passed and retrieval_iteration >= max_retrieval_iterations
        )

        mutation: str | None = (
            verdict.mutation_action.value if verdict.mutation_action else None
        )

        log.info(
            "retrieval/source_grader: verdict",
            passed=verdict.passed,
            score=verdict.score,
            iteration=retrieval_iteration,
            low_confidence=low_confidence,
            mutation_action=mutation,
        )

        return {
            "source_grade": verdict,
            "mutation_action": mutation,
            "retrieval_iteration": retrieval_iteration,
            "low_confidence": low_confidence,
        }

    except Exception as exc:
        msg = "retrieval subgraph source_grader node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


# ---------------------------------------------------------------------------
# Subgraph factory
# ---------------------------------------------------------------------------

def build_retrieval_subgraph() -> object:
    """Build and compile the retrieval & evidence loop subgraph.

    Topology::

        START -> tool_calls -> normalize -> deduplication
              -> save_checkpoint -> source_grader
        source_grader --pass--> END
        source_grader --fail, iter<max--> tool_calls
        source_grader --fail, iter>=max--> END (low_confidence set)

    Returns
    -------
    CompiledStateGraph
        A compiled LangGraph subgraph ready to be embedded as a node in the
        parent graph via ``parent.add_node("retrieval_evidence", subgraph)``.
    """
    try:
        builder = StateGraph(GraphState)

        builder.add_node("tool_calls", _tool_calls)
        builder.add_node("normalize", _normalize)
        builder.add_node("deduplication", _deduplication)
        builder.add_node("save_checkpoint", _save_checkpoint)
        builder.add_node("source_grader", _source_grader)

        # Linear pipeline
        builder.add_edge(START, "tool_calls")
        builder.add_edge("tool_calls", "normalize")
        builder.add_edge("normalize", "deduplication")
        builder.add_edge("deduplication", "save_checkpoint")
        builder.add_edge("save_checkpoint", "source_grader")

        # Conditional exit or loop-back
        builder.add_conditional_edges(
            "source_grader",
            route_after_source_grader,
            {
                "tool_calls": "tool_calls",
                END: END,
            },
        )

        compiled = builder.compile()
        log.info("retrieval_evidence subgraph compiled successfully")
        return compiled

    except Exception as exc:
        msg = "Failed to build retrieval_evidence subgraph"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
