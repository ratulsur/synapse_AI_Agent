"""Agents: section writers (Intro / Body / Conclusion), run in parallel.

Each writer consumes a ``SectionSpec`` + the source pool and produces a
``schemas.section.Section`` with ``cited_source_ids`` populated.

Signatures (called by graph.subgraphs.section_drafting):
    write_intro(state, spec)      -> Section
    write_body(state, spec)       -> Section
    write_conclusion(state, spec) -> Section

Prompts: prompts.templates writer SYSTEM blocks (one per role) + the shared
WRITER_USER template. The LLM returns a narrow ``_WriterOutput`` (prose + cited
ids) via structured output; we assemble the full ``Section`` here so spec_id /
heading / status are set correctly and citations are filtered to ids that
actually exist in state (a fabricated id is dropped here as a first line of
defence; the grounding grader is the real check).

Owner: agent-prompt-engineer
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents._common import (
    format_persona,
    format_plan,
    format_sources,
    get_llm,
    source_ids,
)
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import (
    PROMPT_VERSIONS,
    WRITE_BODY_SYSTEM,
    WRITE_CONCLUSION_SYSTEM,
    WRITE_INTRO_SYSTEM,
    WRITER_USER,
)
from schemas.plan import SectionSpec
from schemas.section import Section
from schemas.source import Source


class _WriterOutput(BaseModel):
    """Narrow structured output for a single section writer."""

    content: str = Field(description="The drafted prose for this section.")
    cited_source_ids: list[str] = Field(
        default_factory=list,
        description="Source.id values actually relied on (must come from the provided list).",
    )


def _write_section(
    state: GraphState, spec: SectionSpec, system_prompt: str, role: str
) -> Section:
    """Shared writer body: build the prompt, call the LLM, assemble a Section."""
    query: str = state.get("query", "")
    analyst = state.get("analyst")
    plan = state.get("plan")
    sources: list[Source] = state.get("sources") or []
    allowed_ids = set(source_ids(sources))

    log.info(
        "writer: drafting section",
        role=role,
        prompt_version=PROMPT_VERSIONS[role],
        section_id=spec.id,
        source_count=len(sources),
    )

    llm = get_llm().with_structured_output(_WriterOutput)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=WRITER_USER.format(
                query=query,
                persona=format_persona(analyst),
                plan=format_plan(plan),
                section_id=spec.id,
                heading=spec.heading,
                intent=spec.intent or "N/A",
                sources=format_sources(sources),
            )
        ),
    ]
    out: _WriterOutput = llm.invoke(messages)

    # Defensive: keep only citations that resolve to a real saved source.
    cited = [cid for cid in out.cited_source_ids if cid in allowed_ids]
    if len(cited) != len(out.cited_source_ids):
        log.warning(
            "writer: dropped fabricated/unknown citation ids",
            role=role,
            section_id=spec.id,
            kept=cited,
            raw=out.cited_source_ids,
        )

    return Section(
        spec_id=spec.id,
        heading=spec.heading,
        content=out.content,
        cited_source_ids=cited,
        status="drafted",
        grounded=False,
        revise_count=0,
    )


def write_intro(state: GraphState, spec: SectionSpec) -> Section:
    """Draft the introduction section."""
    try:
        return _write_section(state, spec, WRITE_INTRO_SYSTEM, "write_intro")
    except Exception as exc:
        msg = "write_intro agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def write_body(state: GraphState, spec: SectionSpec) -> Section:
    """Draft the body / main-analysis section."""
    try:
        return _write_section(state, spec, WRITE_BODY_SYSTEM, "write_body")
    except Exception as exc:
        msg = "write_body agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def write_conclusion(state: GraphState, spec: SectionSpec) -> Section:
    """Draft the conclusion section."""
    try:
        return _write_section(state, spec, WRITE_CONCLUSION_SYSTEM, "write_conclusion")
    except Exception as exc:
        msg = "write_conclusion agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
