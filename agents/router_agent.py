"""Agent: Query Router -- multi-label domain classification.

Input:  GraphState (reads ``query``).
Output: list[schemas.routing.RouteLabel] over the canonical DOMAINS, with a
        GENERIC fallback when nothing specific fires.
Prompt: prompts.templates.ROUTER_SYSTEM / ROUTER_USER (version 'router').

LangChain structured output cannot return a bare ``list``, so we wrap the labels
in a small ``_RouterOutput`` Pydantic model for the LLM call and unwrap to the
``list[RouteLabel]`` the ``query_router`` node expects. Invalid/duplicate labels
are filtered here; the node also validates, so this is defence in depth.

Owner: Ratul Sur
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents._common import get_llm
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import PROMPT_VERSIONS, ROUTER_SYSTEM, ROUTER_USER
from schemas.routing import DOMAINS, GENERIC_DOMAIN, RouteLabel


class _RouterOutput(BaseModel):
    """Structured-output wrapper: the multi-label result of the router."""

    labels: list[RouteLabel] = Field(
        default_factory=list,
        description="One or more domain labels; GENERIC alone when nothing fits.",
    )


def run_router(state: GraphState) -> list[RouteLabel]:
    """Classify the query into one or more retrieval domains (multi-label).

    Args:
        state: GraphState; ``query`` is read.

    Returns:
        list[RouteLabel]: validated, de-duplicated labels (never empty;
        ``[GENERIC]`` on fallback).
    """
    try:
        query: str = state.get("query", "")
        log.info(
            "run_router: classifying",
            prompt_version=PROMPT_VERSIONS["router"],
            query_preview=query[:80],
        )

        llm = get_llm().with_structured_output(_RouterOutput)
        messages = [
            SystemMessage(content=ROUTER_SYSTEM.format(domain_list=", ".join(DOMAINS))),
            HumanMessage(content=ROUTER_USER.format(query=query)),
        ]
        result: _RouterOutput = llm.invoke(messages)

        # Validate against the canonical set and de-duplicate (keep first/highest).
        seen: set[str] = set()
        valid: list[RouteLabel] = []
        for lbl in result.labels:
            if lbl.domain in DOMAINS and lbl.domain not in seen:
                seen.add(lbl.domain)
                valid.append(lbl)

        if not valid:
            log.warning("run_router: no valid labels, GENERIC fallback")
            valid = [RouteLabel(domain=GENERIC_DOMAIN, confidence=1.0)]

        log.info("run_router: labels", domains=[l.domain for l in valid])
        return valid

    except Exception as exc:
        msg = "run_router agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
