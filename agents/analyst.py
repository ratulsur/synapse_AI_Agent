"""Agent: Create Analyst -- frames the analyst role/persona from the query.

Input:  GraphState (reads ``query``).
Output: schemas.analyst.AnalystPersona (expertise, voice, stance).
Prompt: prompts.templates.ANALYST_SYSTEM / ANALYST_USER (version 'analyst').

The persona is produced with ``.with_structured_output(AnalystPersona)`` so the
return value is already the typed schema object the ``create_analyst`` node
expects.

Owner: Ratul Sur
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agents._common import get_llm
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import ANALYST_SYSTEM, ANALYST_USER, PROMPT_VERSIONS
from schemas.analyst import AnalystPersona


def run_analyst(state: GraphState) -> AnalystPersona:
    """Frame the analyst persona for the run.

    Args:
        state: GraphState; ``query`` is read.

    Returns:
        AnalystPersona: typed persona (expertise / voice / stance).
    """
    try:
        query: str = state.get("query", "")
        log.info(
            "run_analyst: framing persona",
            prompt_version=PROMPT_VERSIONS["analyst"],
            query_preview=query[:80],
        )

        llm = get_llm().with_structured_output(AnalystPersona)
        messages = [
            SystemMessage(content=ANALYST_SYSTEM),
            HumanMessage(content=ANALYST_USER.format(query=query)),
        ]
        persona: AnalystPersona = llm.invoke(messages)

        log.info(
            "run_analyst: persona produced",
            expertise=persona.expertise,
            voice=persona.voice,
            stance=persona.stance,
        )
        return persona

    except Exception as exc:
        msg = "run_analyst agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
