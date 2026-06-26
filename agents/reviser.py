"""Agent: Revise Section.

Rewrites a SINGLE ungrounded section (ADR-005, per-section revise loop) using the
grounding grader's rationale + the section's sources, to remove unsupported
claims and fix citations.

Signature (called by graph.nodes.revise_section):
    run_reviser(state, section) -> Section

Prompt: prompts.templates.REVISER_SYSTEM / REVISER_USER (version 'reviser').

The revised Section is returned with ``revise_count`` incremented and
``grounded=False`` / ``status='drafted'`` -- the grounding grader re-judges it on
the next pass. Loop termination is guaranteed by the node's ``revise_iteration``
counter against ``max_revise_iterations``; this agent does not gate the loop.

Owner: Ratul Sur
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents._common import format_sources, get_llm, source_ids
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import PROMPT_VERSIONS, REVISER_SYSTEM, REVISER_USER
from schemas.grading import GraderVerdict
from schemas.section import Section
from schemas.source import Source


class _ReviserOutput(BaseModel):
    """Narrow structured output for a section revision."""

    content: str = Field(description="The revised, fully grounded section prose.")
    cited_source_ids: list[str] = Field(
        default_factory=list,
        description="Source.id values the revised draft relies on (from the provided list).",
    )


def run_reviser(state: GraphState, section: Section) -> Section:
    """Rewrite one ungrounded section so every claim traces to a cited source.

    Args:
        state:   GraphState; reads ``query``, ``sources``, ``grounding_grade``.
        section: the Section to revise.

    Returns:
        Section: revised draft with ``revise_count`` incremented.
    """
    try:
        query: str = state.get("query", "")
        sources: list[Source] = state.get("sources") or []
        allowed_ids = set(source_ids(sources))

        grade: GraderVerdict | None = state.get("grounding_grade")
        rationale = grade.rationale if grade and grade.rationale else "(no rationale provided)"

        log.info(
            "run_reviser: revising section",
            prompt_version=PROMPT_VERSIONS["reviser"],
            section_id=section.spec_id,
            revise_count=section.revise_count,
        )

        llm = get_llm().with_structured_output(_ReviserOutput)
        messages = [
            SystemMessage(content=REVISER_SYSTEM),
            HumanMessage(
                content=REVISER_USER.format(
                    query=query,
                    section_id=section.spec_id,
                    heading=section.heading,
                    draft=section.content or "(empty)",
                    rationale=rationale,
                    sources=format_sources(sources),
                )
            ),
        ]
        out: _ReviserOutput = llm.invoke(messages)

        cited = [cid for cid in out.cited_source_ids if cid in allowed_ids]
        if len(cited) != len(out.cited_source_ids):
            log.warning(
                "run_reviser: dropped fabricated/unknown citation ids",
                section_id=section.spec_id,
                kept=cited,
                raw=out.cited_source_ids,
            )

        revised = Section(
            spec_id=section.spec_id,
            heading=section.heading,
            content=out.content,
            cited_source_ids=cited,
            status="drafted",
            grounded=False,
            revise_count=section.revise_count + 1,
        )
        log.info(
            "run_reviser: section revised",
            section_id=revised.spec_id,
            revise_count=revised.revise_count,
            cited=revised.cited_source_ids,
        )
        return revised

    except Exception as exc:
        msg = "run_reviser agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
