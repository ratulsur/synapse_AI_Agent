"""Shared helpers for the LLM reasoning units in ``agents/``.

This is a private support module for the agent layer. It centralises three
concerns so each agent stays focused on its prompt + output schema:

* ``get_llm()``          -- a process-cached chat LLM (provider chosen by the
                            ``LLM_PROVIDER`` env var via ``ModelLoader``).
* prompt context formatters -- turn typed state objects (Source, ReportPlan,
                            Section, AnalystPersona) into compact, deterministic
                            strings that slot into the prompt templates.
* ``load_rubric()``      -- read an LLM-judge rubric markdown file from
                            ``prompts/rubrics/`` so the graders inject the exact
                            gradeable criteria into their system prompt.

It contains NO prompt text (that lives in ``prompts/templates.py``) and NO graph
wiring. It is imported by the agent modules only.

Owner: Ratul Sur
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from log import GLOBAL_LOGGER as log

if TYPE_CHECKING:  # pragma: no cover - typing only
    from schemas.analyst import AnalystPersona
    from schemas.plan import ReportPlan
    from schemas.section import Section
    from schemas.source import Source


# ---------------------------------------------------------------------------
# LLM accessor
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_llm():
    """Return a process-cached chat LLM.

    Provider selection (openai / google / groq) is handled inside
    ``ModelLoader.load_llm()`` via the ``LLM_PROVIDER`` env var. We cache the
    instance so the many agent calls in a single run do not re-read config or
    re-instantiate the client on every node.
    """
    from utils.model_loader import ModelLoader

    return ModelLoader().load_llm()


# ---------------------------------------------------------------------------
# Prompt-context formatters (deterministic, side-effect free)
# ---------------------------------------------------------------------------

def format_persona(analyst: "AnalystPersona | None") -> str:
    """Render the analyst persona for inclusion in a writer/planner prompt."""
    if analyst is None:
        return "expertise: generalist | voice: clear and informative | stance: objective"
    return (
        f"expertise: {analyst.expertise} | "
        f"voice: {analyst.voice} | "
        f"stance: {analyst.stance}"
    )


def format_plan(plan: "ReportPlan | None") -> str:
    """Render a ReportPlan (audience/length/tone + section specs) as text."""
    if plan is None:
        return "(no plan available)"
    lines = [
        f"audience: {plan.audience}",
        f"length: {plan.length}",
        f"tone: {plan.tone}",
        "sections:",
    ]
    for spec in plan.sorted_sections():
        lines.append(
            f"  - [{spec.id}] {spec.heading} (order {spec.order}) -> {spec.intent or 'N/A'}"
        )
    return "\n".join(lines)


def format_sources(
    sources: "list[Source] | None",
    max_sources: int = 24,
    snippet_chars: int = 700,
) -> str:
    """Render the evidence pool as a numbered, citable list.

    Each entry leads with the stable ``Source.id`` (the value writers must put
    in ``cited_source_ids`` and graders trace claims back to).
    """
    if not sources:
        return "(no sources retrieved)"
    entries: list[str] = []
    for src in sources[:max_sources]:
        snippet = (src.content or "").strip().replace("\n", " ")
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars] + " ..."
        entries.append(
            f"- id={src.id} | domain={src.domain} | score={src.score:.2f} | "
            f"title={src.title!r} | url={src.url}\n  excerpt: {snippet or '(empty)'}"
        )
    return "\n".join(entries)


def source_ids(sources: "list[Source] | None") -> list[str]:
    """Return the list of available Source.id values (citation whitelist)."""
    return [s.id for s in (sources or [])]


def select_sources_for_ids(
    sources: "list[Source] | None", ids: list[str]
) -> "list[Source]":
    """Return the subset of ``sources`` whose id is in ``ids`` (order of ids)."""
    by_id = {s.id: s for s in (sources or [])}
    return [by_id[i] for i in ids if i in by_id]


def format_sections_with_evidence(
    sections: "list[Section] | None",
    sources: "list[Source] | None",
    snippet_chars: int = 600,
) -> str:
    """Render each section's prose alongside the content of its cited sources.

    This is the exact view the grounding grader judges: claim text on one side,
    the evidence the section claims to rest on (its ``cited_source_ids``) on the
    other.
    """
    if not sections:
        return "(no sections drafted)"
    by_id = {s.id: s for s in (sources or [])}
    blocks: list[str] = []
    for sec in sections:
        cited_lines: list[str] = []
        for cid in sec.cited_source_ids:
            src = by_id.get(cid)
            if src is None:
                cited_lines.append(f"    - id={cid}: [MISSING - id not found in saved sources]")
                continue
            snippet = (src.content or "").strip().replace("\n", " ")
            if len(snippet) > snippet_chars:
                snippet = snippet[:snippet_chars] + " ..."
            cited_lines.append(f"    - id={cid}: {snippet or '(empty)'}")
        cited_block = "\n".join(cited_lines) if cited_lines else "    (no sources cited)"
        blocks.append(
            f"### section_id={sec.spec_id} | heading={sec.heading!r}\n"
            f"DRAFT:\n{sec.content or '(empty)'}\n"
            f"CITED SOURCES:\n{cited_block}"
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Rubric loader (LLM-judge criteria live in prompts/rubrics/*.md)
# ---------------------------------------------------------------------------

_RUBRICS_DIR = Path(__file__).resolve().parents[1] / "prompts" / "rubrics"


@lru_cache(maxsize=8)
def load_rubric(filename: str) -> str:
    """Load a grader rubric markdown file from ``prompts/rubrics/``.

    Cached because the rubric is static across a run. On a missing/empty file we
    log a warning and return an empty string so the grader degrades to its
    in-prompt criteria rather than crashing.
    """
    path = _RUBRICS_DIR / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            log.warning("load_rubric: rubric file is empty", filename=filename)
        return text
    except FileNotFoundError:
        log.warning("load_rubric: rubric file not found", filename=filename, path=str(path))
        return ""
