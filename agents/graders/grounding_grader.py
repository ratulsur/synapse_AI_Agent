"""Grader: Grounding Grader (LLM judge: claims vs cited sources).

For each drafted section, checks every non-trivial factual claim against the
section's cited sources and flags ungrounded sections. Returns
``failing_section_ids`` so the router sends ONLY the failing section(s) to Revise
Section (ADR-005, per-section revise loop).

Signature (called by graph.nodes.grounding_grader):
    run_grounding_grader(state) -> GraderVerdict

Prompt: prompts.templates.GROUNDING_GRADER_SYSTEM / GROUNDING_GRADER_USER.
Rubric: prompts/rubrics/grounding_grader_rubric.md (injected into the system prompt).

Termination note: this grader does not gate the loop -- the ``revise_section``
node increments ``revise_iteration`` and ``route_after_grounding_grader``
enforces ``max_revise_iterations``. The grader only reports which sections fail.
We also clamp ``failing_section_ids`` to ids that actually exist so the router
can never spin on a hallucinated section id.

Owner: agent-prompt-engineer
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agents._common import format_sections_with_evidence, get_llm, load_rubric
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import (
    GROUNDING_GRADER_SYSTEM,
    GROUNDING_GRADER_USER,
    PROMPT_VERSIONS,
)
from schemas.grading import GraderVerdict
from schemas.section import Section
from schemas.source import Source

_RUBRIC_FILE = "grounding_grader_rubric.md"


def run_grounding_grader(state: GraphState) -> GraderVerdict:
    """Judge per-section grounding of drafted sections against their sources.

    Args:
        state: GraphState; reads ``query``, ``sections``, ``sources``.

    Returns:
        GraderVerdict: passed / score / rationale / failing_section_ids.
    """
    try:
        query: str = state.get("query", "")
        sections: list[Section] = state.get("sections") or []
        sources: list[Source] = state.get("sources") or []

        # Only judge sections that have actually been drafted.
        drafted = [s for s in sections if s.content.strip()]
        valid_ids = {s.spec_id for s in drafted}

        log.info(
            "run_grounding_grader: grading sections",
            prompt_version=PROMPT_VERSIONS["grounding_grader"],
            section_count=len(drafted),
            source_count=len(sources),
        )

        if not drafted:
            verdict = GraderVerdict(
                passed=True,
                score=1.0,
                rationale="No drafted sections to grade; nothing to ground.",
                failing_section_ids=[],
            )
            log.info("run_grounding_grader: nothing to grade -> pass")
            return verdict

        llm = get_llm().with_structured_output(GraderVerdict)
        messages = [
            SystemMessage(
                content=GROUNDING_GRADER_SYSTEM.format(rubric=load_rubric(_RUBRIC_FILE))
            ),
            HumanMessage(
                content=GROUNDING_GRADER_USER.format(
                    query=query,
                    sections_with_evidence=format_sections_with_evidence(drafted, sources),
                )
            ),
        ]
        verdict: GraderVerdict = llm.invoke(messages)

        verdict = _enforce_invariants(verdict, valid_ids)

        log.info(
            "run_grounding_grader: verdict",
            passed=verdict.passed,
            score=verdict.score,
            failing_section_ids=verdict.failing_section_ids,
        )
        return verdict

    except Exception as exc:
        msg = "run_grounding_grader agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _enforce_invariants(verdict: GraderVerdict, valid_ids: set[str]) -> GraderVerdict:
    """Keep the verdict consistent for the grounding router.

    * Drop any failing id that is not a real drafted section (anti-hallucination;
      prevents the revise loop spinning on a non-existent section).
    * Re-derive ``passed`` from the cleaned ``failing_section_ids`` so passed and
      the list can never disagree (the router branches on the list).
    * Clear ``mutation_action`` (unused by this grader).
    """
    cleaned = [sid for sid in verdict.failing_section_ids if sid in valid_ids]
    if len(cleaned) != len(verdict.failing_section_ids):
        log.warning(
            "run_grounding_grader: dropped unknown failing_section_ids",
            kept=cleaned,
            raw=verdict.failing_section_ids,
        )
    verdict.failing_section_ids = cleaned
    verdict.passed = len(cleaned) == 0
    verdict.mutation_action = None
    return verdict
