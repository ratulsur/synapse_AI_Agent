"""Agent: Equity Research Analyst — produces a K-pick stock selection record.

Input:  universe_symbols, context_data (OHLCV summary), k, mode, as_of_date.
Output: list[PickItem] of exactly k items.
LLM:    get_llm() from agents._common (provider chosen by LLM_PROVIDER env var).

The agent asks the LLM to select K stocks from the universe snapshot,
providing recent OHLCV context to ground the decision. Output is parsed
via structured_output into a Pydantic model.

Fallback: if the LLM call fails or produces the wrong number of picks, the
node falls back to a random selection with default confidence/regime/rationale
so the harness can always record a valid PickRecord (degraded but not crashed).

Owner: Ratul Sur
"""

from __future__ import annotations

import random
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agents._common import get_llm
from log import GLOBAL_LOGGER as log

try:
    from evals.stock_picker.models import PickItem
except ImportError:  # pragma: no cover
    PickItem = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# LLM output schema — wraps list[PickItem] so structured_output works
# ---------------------------------------------------------------------------


class _PickList(BaseModel):
    picks: list[PickItem]  # type: ignore[valid-type]


_SYSTEM = """\
You are a senior equity research analyst specialising in NSE-listed stocks.
Your task is to select exactly {k} stocks from the provided universe for a
{mode} research experiment as of {as_of_date}.

Rules:
- Return exactly {k} picks — no more, no fewer.
- Each pick must include: symbol (must be from the universe), direction
  ("long" or "short"), confidence in [0.0, 1.0], regime_label (one of:
  BULL, BEAR, SIDEWAYS, VOLATILE, RECOVERY), and a concise rationale.
- "short" direction is only valid for F&O-eligible names.
- Base your reasoning on the provided market context data. Do not invent data.
- Confidence must reflect genuine conviction — use the full [0, 1] range.
"""

_USER = """\
Universe ({n_symbols} symbols, showing first 80):
{universe_sample}

Recent 30-day OHLCV context (symbol → last_close, pct_change_30d, avg_volume):
{context_block}

Select exactly {k} stocks. Return a JSON object with a "picks" array.
"""


def _format_context(context_data: dict[str, dict[str, Any]]) -> str:
    lines = []
    for sym, ctx in list(context_data.items())[:50]:
        last_close = ctx.get("last_close", "N/A")
        pct30 = ctx.get("pct_change_30d", "N/A")
        vol = ctx.get("avg_volume", "N/A")
        if isinstance(last_close, float):
            last_close = f"{last_close:.2f}"
        if isinstance(pct30, float):
            pct30 = f"{pct30:.2%}"
        if isinstance(vol, float):
            vol = f"{vol:,.0f}"
        lines.append(f"  {sym}: close={last_close}, 30d_chg={pct30}, avg_vol={vol}")
    return "\n".join(lines)


def _random_fallback(universe_symbols: list[str], k: int) -> list[PickItem]:
    """Return k random picks with default fields when LLM is unavailable."""
    chosen = random.sample(universe_symbols, min(k, len(universe_symbols)))
    return [
        PickItem(
            symbol=sym,
            direction="long",
            confidence=0.5,
            regime_label="GENERIC",
            rationale="LLM unavailable — random fallback pick",
        )
        for sym in chosen
    ]


def run_equity_research_analyst(
    universe_symbols: list[str],
    context_data: dict[str, dict[str, Any]],
    k: int,
    mode: str,
    as_of_date: str,
) -> list[PickItem]:
    """Produce exactly k PickItem selections from the given universe.

    Args:
        universe_symbols: The frozen universe constituent list for this run.
        context_data:     {symbol: {last_close, pct_change_30d, avg_volume}}.
        k:                Number of picks (enforced; harness rejects != k).
        mode:             "forward" or "backtest".
        as_of_date:       ISO date string "YYYY-MM-DD".

    Returns:
        list[PickItem] of exactly k items. Falls back to random selection
        if the LLM fails or returns the wrong count.
    """
    if PickItem is None:
        log.error("run_equity_research_analyst: evals.stock_picker not importable")
        return []

    n_symbols = len(universe_symbols)
    universe_sample = ", ".join(universe_symbols[:80])
    context_block = _format_context(context_data)

    system_msg = _SYSTEM.format(k=k, mode=mode, as_of_date=as_of_date)
    user_msg = _USER.format(
        n_symbols=n_symbols,
        universe_sample=universe_sample,
        context_block=context_block,
        k=k,
    )

    try:
        llm = get_llm().with_structured_output(_PickList)
        result: _PickList = llm.invoke(
            [SystemMessage(content=system_msg), HumanMessage(content=user_msg)]
        )
        picks = result.picks

        # Enforce universe membership
        universe_set = set(universe_symbols)
        valid = [p for p in picks if p.symbol in universe_set]
        if len(valid) != k:
            log.warning(
                "run_equity_research_analyst: LLM returned wrong count after filtering",
                returned=len(picks),
                valid=len(valid),
                k=k,
            )
            raise ValueError(f"Expected {k} picks, got {len(valid)} valid ones")

        log.info(
            "run_equity_research_analyst: picks produced",
            k=k,
            mode=mode,
            as_of_date=as_of_date,
            symbols=[p.symbol for p in valid],
        )
        return valid

    except Exception as exc:
        log.warning(
            "run_equity_research_analyst: LLM failed, using random fallback",
            error=str(exc),
        )
        return _random_fallback(universe_symbols, k)
