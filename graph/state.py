"""Top-level LangGraph state schema for the research-report agent.

This is the single typed dict that flows through every node and subgraph.
LangGraph merges partial-dict updates returned by nodes into this state; fields
that accumulate across nodes are annotated with reducer functions.

Reducer contract
----------------
add_sources_reducer   -- Accumulate Source[] deduping by Source.id (highest
                         score wins when the same id appears twice).  The
                         dedup key ensures the subgraph fan-out does not
                         double-count sources already in the parent state.
merge_sections_reducer -- Merge Section[] by spec_id; the most-recent write
                          for a given spec_id wins (used by parallel writers
                          and revise cycles).
add_messages          -- LangGraph built-in; deduplicates by message id.
operator.add          -- Simple list concatenation for the errors list
                         (errors are append-only across the graph).

Owner: Ratul Sur
"""

from __future__ import annotations

import operator
from typing import Annotated

from langgraph.graph.message import add_messages

from schemas.analyst import AnalystPersona
from schemas.grading import GraderVerdict
from schemas.plan import ReportPlan
from schemas.section import Section
from schemas.source import Source

# ---------------------------------------------------------------------------
# Reducer helpers
# ---------------------------------------------------------------------------


def add_sources_reducer(left: list[Source], right: list[Source]) -> list[Source]:
    """Accumulate sources, deduplicating by Source.id.

    When the same id appears in both ``left`` and ``right``, the version in
    ``left`` (already in the accumulated state) is retained.  This makes the
    reducer safe for use with subgraphs that receive the full parent state and
    return an augmented copy -- no double-counting occurs.
    """
    if not right:
        return left
    existing_ids: set[str] = {s.id for s in left}
    new_sources = [s for s in right if s.id not in existing_ids]
    return left + new_sources


def merge_sections_reducer(left: list[Section], right: list[Section]) -> list[Section]:
    """Merge sections by spec_id; the most-recent write per spec_id wins.

    This supports:
    * Parallel writers that each emit a single section (fan-out / fan-in).
    * The revise loop that overwrites only the failing section(s).
    * The write-node scaffold that pre-creates pending stubs.
    """
    merged: dict[str, Section] = {s.spec_id: s for s in left}
    for s in right:
        merged[s.spec_id] = s  # newest write wins
    # Preserve insertion order from left, then append any new spec_ids from right
    ordered: list[Section] = []
    seen: set[str] = set()
    for s in left:
        ordered.append(merged[s.spec_id])
        seen.add(s.spec_id)
    for s in right:
        if s.spec_id not in seen:
            ordered.append(merged[s.spec_id])
            seen.add(s.spec_id)
    return ordered


# ---------------------------------------------------------------------------
# GraphState TypedDict
# ---------------------------------------------------------------------------

class GraphState(dict):  # noqa: FURB118 -- LangGraph requires a mapping, TypedDict extends dict
    """The single typed object flowing through every node and subgraph.

    Using ``TypedDict`` annotation style via ``Annotated`` fields for LangGraph's
    reducer mechanism.  Nodes return a **partial dict** with only the keys they
    update; LangGraph merges those updates using the reducer for each key.

    Fields with no ``Annotated`` reducer use last-write-wins semantics.
    """
    pass


# Re-declare as a proper TypedDict so type-checkers understand the shape.
# LangGraph accepts any TypedDict subclass as the state type.
from typing import TypedDict  # noqa: E402 -- after the imports above


class GraphState(TypedDict, total=False):  # type: ignore[no-redef]
    """Typed state flowing through the Synapse research-report agent graph.

    All fields are Optional (``total=False``) so nodes can return partial
    updates without raising KeyError on first access via ``state.get()``.
    """

    # --- Inputs / framing ---
    query: str                        # original user research question
    analyst: AnalystPersona           # role/persona from Create Analyst node
    plan: ReportPlan                  # audience, length, tone, section specs
    plan_approved: bool               # set True by Human-in-the-loop approve

    # --- Routing ---
    route_labels: list[str]           # multi-label output of Query Router
    active_domains: list[str]         # selected subset of DOMAINS to retrieve against

    # --- Retrieval / evidence loop ---
    sources: Annotated[list[Source], add_sources_reducer]
    retrieval_iteration: int          # current loop count (incremented in source_grader node)
    max_retrieval_iterations: int     # iteration cap (set from config; default 3)
    source_grade: GraderVerdict       # last Source Grader judgement
    mutation_action: str | None       # 'reformulate' | 'widen' | 'reroute'
    low_confidence: bool              # True when loop exits without passing grade

    # --- Drafting / grounding loop ---
    sections: Annotated[list[Section], merge_sections_reducer]
    grounding_grade: GraderVerdict    # last Grounding Grader judgement
    revise_iteration: int             # grounding revise loop count (incremented in revise_section)
    max_revise_iterations: int        # cap for grounding loop (set from config; default 2)

    # --- Output ---
    report: str                       # assembled report string
    final_answer: str                 # terminal payload returned to caller

    # --- Bookkeeping ---
    messages: Annotated[list, add_messages]   # ReAct / agent scratch (LangChain messages)
    errors: Annotated[list[str], operator.add]  # append-only error log
