"""Agent: Scope & Plan -- derives audience, length, tone, and section specs.

Input:  GraphState (reads ``query``, ``analyst``, and on a revise cycle any
        prior ``plan``).
Output: schemas.plan.ReportPlan (exactly three sections: intro / body /
        conclusion, matching the three-writer drafting subgraph).
Prompt: prompts.templates.PLANNER_SYSTEM / PLANNER_USER (version 'planner').

The plan is produced with ``.with_structured_output(ReportPlan)``. We then
normalise the section set to the three canonical ids the drafting subgraph wires
(intro / body / conclusion) so downstream writers always find their spec.

Owner: agent-prompt-engineer
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agents._common import format_persona, format_plan, get_llm
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import PLANNER_SYSTEM, PLANNER_USER, PROMPT_VERSIONS
from schemas.plan import ReportPlan, SectionSpec
from utils.config_loader import load_config

# The drafting subgraph hard-wires exactly these three writer roles/ids.
_CANONICAL_IDS: list[str] = ["intro", "body", "conclusion"]
_DEFAULT_HEADINGS: dict[str, str] = {
    "intro": "Introduction",
    "body": "Main Analysis",
    "conclusion": "Conclusion",
}


def run_planner(state: GraphState) -> ReportPlan:
    """Produce (or refine) the ReportPlan for the query.

    Args:
        state: GraphState; reads ``query``, ``analyst``, optional prior ``plan``.

    Returns:
        ReportPlan: audience/length/tone + exactly three canonical sections.
    """
    try:
        query: str = state.get("query", "")
        analyst = state.get("analyst")
        prior_plan = state.get("plan")

        agent_cfg: dict = load_config().get("agent", {})

        log.info(
            "run_planner: scoping plan",
            prompt_version=PROMPT_VERSIONS["planner"],
            query_preview=query[:80],
            revising=prior_plan is not None,
        )

        llm = get_llm().with_structured_output(ReportPlan)
        messages = [
            SystemMessage(content=PLANNER_SYSTEM),
            HumanMessage(
                content=PLANNER_USER.format(
                    query=query,
                    persona=format_persona(analyst),
                    default_audience=agent_cfg.get("default_audience", "general"),
                    default_length=agent_cfg.get("default_length", "medium"),
                    default_tone=agent_cfg.get("default_tone", "neutral"),
                    prior_plan=format_plan(prior_plan) if prior_plan else "(none)",
                    feedback=state.get("plan_feedback", "(none)"),
                )
            ),
        ]
        plan: ReportPlan = llm.invoke(messages)

        plan = _normalise_sections(plan, query)

        log.info(
            "run_planner: plan produced",
            audience=plan.audience,
            length=plan.length,
            tone=plan.tone,
            sections=[s.id for s in plan.sorted_sections()],
        )
        return plan

    except Exception as exc:
        msg = "run_planner agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def _normalise_sections(plan: ReportPlan, query: str) -> ReportPlan:
    """Force the section set onto the three canonical ids the writers expect.

    The model is instructed to emit intro/body/conclusion, but we defend the
    drafting subgraph's hard contract: map by id when present, else by order,
    and backfill any missing role with a minimal spec.
    """
    by_id = {s.id: s for s in plan.sections}
    ordered = plan.sorted_sections()
    fixed: list[SectionSpec] = []

    for idx, canonical in enumerate(_CANONICAL_IDS):
        src: SectionSpec | None = by_id.get(canonical)
        if src is None and idx < len(ordered):
            src = ordered[idx]  # positional fallback if the model used other ids
        if src is None:
            fixed.append(
                SectionSpec(
                    id=canonical,
                    heading=_DEFAULT_HEADINGS[canonical],
                    intent=f"Cover the {canonical} for: {query}",
                    order=idx,
                )
            )
        else:
            fixed.append(
                SectionSpec(
                    id=canonical,
                    heading=src.heading or _DEFAULT_HEADINGS[canonical],
                    intent=src.intent or f"Cover the {canonical} for: {query}",
                    order=idx,
                )
            )

    plan.sections = fixed
    return plan
