"""Random basket baselines and Nifty 50 benchmark fetching.

The random basket baseline controls for the "throw darts" illusion: if
the agent's K-pick return lies within the distribution of M random K-picks
drawn from the same universe, there is no demonstrated skill beyond chance.

All yfinance calls are bulk-fetched to minimise API round-trips.

Owner: Ratul Sur
"""

from __future__ import annotations

import random
import statistics
import uuid
from datetime import datetime, timedelta

import yfinance as yf

from evals.stock_picker.models import PickRecord, RandomBaselineRecord
from evals.stock_picker.universe import get_nifty50_ticker
from log import GLOBAL_LOGGER as log


def get_benchmark_return(entry_date: str, exit_date: str) -> float:
    """Nifty 50 close-to-close return from entry_date to exit_date.

    For intraday (entry_date == exit_date) uses open-to-close of that day.
    Returns 0.0 on any failure so callers always get a numeric value.
    """
    try:
        ticker = get_nifty50_ticker()
        end = (datetime.strptime(exit_date, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
        df = yf.Ticker(ticker).history(start=entry_date, end=end, interval="1d")
        if df.empty:
            return 0.0
        if entry_date == exit_date:
            entry_px = float(df.iloc[0]["Open"])
            exit_px = float(df.iloc[0]["Close"])
        else:
            entry_px = float(df.iloc[0]["Close"])
            exit_rows = df[df.index.strftime("%Y-%m-%d") == exit_date]  # type: ignore[attr-defined]
            exit_px = float(exit_rows.iloc[0]["Close"]) if not exit_rows.empty else float(df.iloc[-1]["Close"])
        return 0.0 if entry_px == 0 else (exit_px - entry_px) / entry_px
    except Exception as exc:
        log.warning("baselines.get_benchmark_return: error", error=str(exc))
        return 0.0


def _bulk_symbol_returns(
    symbols: list[str],
    entry_date: str,
    exit_date: str,
) -> dict[str, float]:
    """Pre-fetch close-to-close returns for all symbols in one yfinance call.

    For intraday (entry_date == exit_date) returns open-to-close.
    Symbols with missing or malformed data are silently dropped from the
    result dict so callers filter to only eligible symbols.
    """
    if not symbols:
        return {}

    end = (datetime.strptime(exit_date, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")

    try:
        df = yf.download(
            symbols,
            start=entry_date,
            end=end,
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
        )
    except Exception as exc:
        log.warning("baselines._bulk_symbol_returns: download failed", error=str(exc))
        return {}

    returns: dict[str, float] = {}
    is_intraday = entry_date == exit_date

    # yfinance returns a MultiIndex frame when multiple tickers are requested.
    # Single-ticker requests produce a flat frame — handle both.
    for sym in symbols:
        try:
            if len(symbols) == 1:
                sym_df = df
            else:
                sym_df = df[sym] if sym in df.columns.get_level_values(0) else None  # type: ignore[index]

            if sym_df is None or sym_df.empty:
                continue

            # Filter to dates within our window
            sym_df = sym_df[
                (sym_df.index.strftime("%Y-%m-%d") >= entry_date)  # type: ignore[attr-defined]
                & (sym_df.index.strftime("%Y-%m-%d") <= exit_date)  # type: ignore[attr-defined]
            ]
            if sym_df.empty:
                continue

            if is_intraday:
                entry_px = float(sym_df.iloc[0]["Open"])
                exit_px = float(sym_df.iloc[0]["Close"])
            else:
                entry_px = float(sym_df.iloc[0]["Close"])
                exit_rows = sym_df[sym_df.index.strftime("%Y-%m-%d") == exit_date]  # type: ignore[attr-defined]
                exit_px = (
                    float(exit_rows.iloc[0]["Close"]) if not exit_rows.empty else float(sym_df.iloc[-1]["Close"])
                )

            if entry_px != 0:
                returns[sym] = (exit_px - entry_px) / entry_px
        except Exception as exc:
            log.debug("baselines._bulk_symbol_returns: skipping symbol", symbol=sym, error=str(exc))

    return returns


def generate_random_baskets(
    universe_symbols: list[str],
    k: int,
    n_baskets: int,
    entry_date: str,
    exit_date: str,
) -> list[float]:
    """Draw n_baskets random K-symbol baskets; return mean return per basket.

    All symbol returns are pre-fetched in a single yfinance bulk call.
    Symbols with missing data are dropped from the eligible pool before
    sampling so each basket only contains valid returns.
    """
    symbol_returns = _bulk_symbol_returns(universe_symbols, entry_date, exit_date)

    eligible = list(symbol_returns.keys())
    if len(eligible) < k:
        log.warning(
            "baselines.generate_random_baskets: fewer eligible symbols than k",
            eligible=len(eligible),
            k=k,
        )
        if not eligible:
            return []
        k = len(eligible)

    basket_means: list[float] = []
    for _ in range(n_baskets):
        basket = random.sample(eligible, k)
        mean_ret = statistics.mean(symbol_returns[sym] for sym in basket)
        basket_means.append(mean_ret)

    return basket_means


def compute_random_baseline(
    pick_record: PickRecord,
    horizon: str,
    entry_date: str,
    exit_date: str,
    n_baskets: int = 1000,
) -> RandomBaselineRecord:
    """Compute a RandomBaselineRecord for one (run, horizon) pair.

    The universe used is derived from the PickRecord's universe_snapshot_id;
    callers must resolve the symbol list before calling here and pass it via
    compute_random_baseline_for_snapshot() or construct their own call.

    This version accepts explicit entry/exit dates so scoring and baseline
    computation share the exact same price window.
    """
    # Universe symbols come from the harness which resolves the snapshot.
    # We can't look up the snapshot here without a ledger reference, so the
    # harness passes entry/exit dates and we fetch returns directly.
    from evals.stock_picker.universe import NIFTY500_SYMBOLS

    # Fallback: use the static NIFTY500 list if snapshot resolution is unavailable.
    universe_symbols = NIFTY500_SYMBOLS

    basket_returns = generate_random_baskets(
        universe_symbols=universe_symbols,
        k=pick_record.k,
        n_baskets=n_baskets,
        entry_date=entry_date,
        exit_date=exit_date,
    )

    if basket_returns:
        mean_ret = statistics.mean(basket_returns)
        std_ret = statistics.stdev(basket_returns) if len(basket_returns) > 1 else 0.0
    else:
        mean_ret = 0.0
        std_ret = 0.0

    return RandomBaselineRecord(
        run_id=pick_record.run_id,
        horizon=horizon,
        n_baskets=len(basket_returns),
        mean_return=mean_ret,
        std_return=std_ret,
        basket_returns=basket_returns,
    )
