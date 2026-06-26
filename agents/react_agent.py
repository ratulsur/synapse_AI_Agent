"""Agent: ReAct tool-use agent for the retrieval loop.

Input:  GraphState (reads ``query``, ``active_domains``, ``mutation_action``).
Output: dict partial-state update with a ``messages`` key (the ReAct scratch:
        the task message, the agent's reasoning/tool-call messages, and any tool
        observations). The retrieval subgraph's ``normalize`` step turns the raw
        hits into typed ``Source`` objects.
Prompt: prompts.templates.REACT_SYSTEM / REACT_USER (version 'react').

Tool binding seam
-----------------
Tools come from ``tools.registry`` (owned by backend-developer) and are still a
stub. This agent therefore:
  * tries ``tools.registry.tools_for(active_domains)`` then ``all_tools()``;
  * if real LangChain tools are returned, runs a bounded reason-act-observe loop
    (capped by ``agent.max_react_steps``) executing tool calls;
  * if the registry is empty/stubbed/raises, DEGRADES to a single no-tool
    reasoning pass (states the search plan) and returns cleanly.
It never crashes on an empty tool layer.

The ``mutation_action`` from the source grader's previous verdict is honoured by
swapping in a different retrieval directive (reformulate / widen / reroute).

Owner: Ratul Sur
"""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agents._common import get_llm
from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from prompts.templates import (
    PROMPT_VERSIONS,
    REACT_MUTATION_DIRECTIVES,
    REACT_SYSTEM,
    REACT_USER,
)
from utils.config_loader import load_config


def _bind_tools(active_domains: list[str]) -> list:
    """Return the bound tool set for the active domains, or [] if unavailable.

    Tolerates a stubbed/empty ``tools.registry`` (the common case during the
    current build phase) without raising.
    """
    try:
        from tools import registry  # type: ignore[import]
    except Exception:
        log.debug("react_agent: tools.registry not importable, no tools bound")
        return []

    for fn_name, args in (("tools_for", (active_domains,)), ("all_tools", ())):
        fn = getattr(registry, fn_name, None)
        if callable(fn):
            try:
                tools = fn(*args)
                if tools:
                    log.info("react_agent: bound tools", source=fn_name, count=len(tools))
                    return list(tools)
            except Exception as exc:  # noqa: BLE001 - tolerate stub factories
                log.debug("react_agent: tool factory unavailable", fn=fn_name, error=str(exc))
    return []


def run_react_agent(state: GraphState) -> dict:
    """Run the ReAct retrieval agent over the active domains.

    Args:
        state: GraphState; reads ``query``, ``active_domains``, ``mutation_action``.

    Returns:
        dict: partial state update ``{"messages": [...]}`` for the subgraph.
    """
    try:
        query: str = state.get("query", "")
        active_domains: list[str] = state.get("active_domains") or ["GENERIC"]
        mutation_action: str | None = state.get("mutation_action")

        directive = REACT_MUTATION_DIRECTIVES.get(
            mutation_action or "none", REACT_MUTATION_DIRECTIVES["none"]
        )
        max_steps: int = int(load_config().get("agent", {}).get("max_react_steps", 4))

        log.info(
            "run_react_agent: starting",
            prompt_version=PROMPT_VERSIONS["react"],
            domains=active_domains,
            mutation_action=mutation_action,
        )

        task = HumanMessage(
            content=REACT_USER.format(
                query=query,
                active_domains=", ".join(active_domains),
                mutation_directive=directive,
            )
        )
        convo = [SystemMessage(content=REACT_SYSTEM), task]

        tools = _bind_tools(active_domains)

        # --- Degraded path: no tools available -> single reasoning pass. ---
        if not tools:
            log.info("run_react_agent: no tools bound, single reasoning pass")
            ai: AIMessage = get_llm().invoke(convo)
            return {"messages": [task, ai]}

        # --- Tooled path: bounded reason-act-observe loop. ---
        tool_map = {t.name: t for t in tools}
        llm_with_tools = get_llm().bind_tools(tools)
        emitted: list = [task]

        for step in range(max_steps):
            ai = llm_with_tools.invoke(convo)
            convo.append(ai)
            emitted.append(ai)

            tool_calls = getattr(ai, "tool_calls", None) or []
            if not tool_calls:
                log.debug("run_react_agent: no further tool calls", step=step)
                break

            for call in tool_calls:
                name = call.get("name", "")
                tool = tool_map.get(name)
                if tool is None:
                    obs = f"[tool '{name}' not found in registry]"
                else:
                    try:
                        obs = str(tool.invoke(call.get("args", {})))
                    except Exception as exc:  # noqa: BLE001 - surface as observation
                        obs = f"[tool '{name}' error: {exc}]"
                tool_msg = ToolMessage(content=obs, tool_call_id=call.get("id", name))
                convo.append(tool_msg)
                emitted.append(tool_msg)

        log.info("run_react_agent: done", messages_emitted=len(emitted))
        return {"messages": emitted}

    except Exception as exc:
        msg = "run_react_agent agent failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
