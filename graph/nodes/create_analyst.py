"""Node: Create Analyst.

Frames the analyst role/persona for the run (expertise, voice, stance) given
the user query.  Delegates to ``agents.analyst``; if that stub raises
``NotImplementedError`` a sensible default AnalystPersona is used so the graph
can continue end-to-end.

Also initialises loop-cap fields (``max_retrieval_iterations``,
``max_revise_iterations``) from config if they are not already present in state.

Owner: backend-developer (persona prompt: agent-prompt-engineer)
"""

from __future__ import annotations

from exception.custom_exception import ResearchAnalystException
from graph.state import GraphState
from log import GLOBAL_LOGGER as log
from schemas.analyst import AnalystPersona
from utils.config_loader import load_config


def create_analyst(state: GraphState) -> dict:
    """Create or refresh the analyst persona and initialise run-level config.

    Returns a partial state update with keys:
        analyst                  -- AnalystPersona
        max_retrieval_iterations -- int (from config if not already in state)
        max_revise_iterations    -- int (from config if not already in state)
    """
    try:
        query: str = state.get("query", "")
        log.info("create_analyst: framing analyst persona", query_preview=query[:80])

        # --- Delegate to agent stub ---
        try:
            from agents.analyst import run_analyst  # type: ignore[import]
            persona: AnalystPersona = run_analyst(state)
        except (ImportError, NotImplementedError, AttributeError):
            # Agent stub not yet implemented -- use a sensible placeholder.
            log.debug("create_analyst: agent stub not ready, using default persona")
            persona = AnalystPersona(
                expertise="generalist researcher",
                voice="clear and informative",
                stance="evidence-based and objective",
            )

        # --- Initialise loop caps from config (caller may override via initial state) ---
        cfg = load_config()
        agent_cfg: dict = cfg.get("agent", {})
        max_retrieval = state.get(
            "max_retrieval_iterations",
            agent_cfg.get("max_retrieval_iterations", 3),
        )
        max_revise = state.get(
            "max_revise_iterations",
            agent_cfg.get("max_revise_iterations", 2),
        )

        log.info(
            "create_analyst: done",
            expertise=persona.expertise,
            max_retrieval_iterations=max_retrieval,
            max_revise_iterations=max_revise,
        )

        return {
            "analyst": persona,
            "max_retrieval_iterations": int(max_retrieval),
            "max_revise_iterations": int(max_revise),
        }

    except Exception as exc:
        msg = "create_analyst node failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
