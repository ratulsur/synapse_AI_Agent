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

Stub behaviour: when any owned layer raises NotImplementedError / ImportError,
the node falls back to a safe no-op so the subgraph topology stays intact and
compilable.

Owner: backend-developer (agent + grader prompts: agent-prompt-engineer)
"""

from __future__ import annotations

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
    """Convert raw tool-hit messages into typed ``Source`` objects."""
    try:
        log.debug("retrieval/normalize: normalising raw hits")

        try:
            from tools.processing.normalize import normalize  # type: ignore[import]
            active_domains: list[str] = state.get("active_domains") or ["GENERIC"]
            domain: str = active_domains[0] if active_domains else "GENERIC"
            raw_hits: list[dict] = []  # agents.react_agent populates messages; stub passes []
            sources: list[Source] = normalize(raw_hits, domain=domain, tool="react")
            return {"sources": sources}
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("retrieval/normalize: normalize stub not ready, returning empty list")
            return {}

    except Exception as exc:
        msg = "retrieval subgraph normalize node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _deduplication(state: GraphState) -> dict:
    """Deduplicate incoming sources against already-accumulated sources."""
    try:
        log.debug("retrieval/deduplication: deduplicating sources")

        try:
            from tools.processing.dedup import dedup  # type: ignore[import]
            existing: list[Source] = state.get("sources") or []
            incoming: list[Source] = []  # normalize populates via state; stub passes []
            merged: list[Source] = dedup(existing, incoming)
            # Return only the truly new sources; add_sources_reducer handles accumulation.
            existing_ids = {s.id for s in existing}
            new_only = [s for s in merged if s.id not in existing_ids]
            return {"sources": new_only} if new_only else {}
        except (ImportError, NotImplementedError, AttributeError):
            log.debug("retrieval/deduplication: dedup stub not ready, no-op")
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
