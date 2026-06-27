"""NSE price fetcher and per-pick outcome scorer.

Uses yfinance with fail-soft: any exception per symbol is logged and
skipped — one broken symbol must never crash a scoring run.

India cost model per EVAL_HARNESS.md §3. All percentages are divided by
100 before being returned as fractions so callers always work in fraction
space (e.g. 0.002 = 0.2%).

Owner: Ratul Sur
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import yfinance as yf

from evals.stock_picker.models import OutcomeRecord, PickItem, PickRecord
from evals.stock_picker.universe import get_nifty50_ticker
from log import GLOBAL_LOGGER as log

# ---------------------------------------------------------------------------
# India cost model (all values in percent per side unless noted)
# ---------------------------------------------------------------------------

COST_MODEL: dict[str, dict[str, float]] = {
    "intraday": {
        "brokerage": 0.03,
        "stt_sell": 0.025,
        "exchange": 0.00345,
        "gst_on_brokerage_and_exchange": 0.18,   # rate applied to (brokerage+exchange) per side
        "sebi": 0.0001,
        "stamp_buy": 0.003,
        "slippage": 0.05,
    },
    "delivery": {   # used for swing + position
        "brokerage": 0.03,
        "stt_sell": 0.1,
        "exchange": 0.00345,
        "gst_on_brokerage_and_exchange": 0.18,
        "sebi": 0.0001,
        "stamp_buy": 0.015,
        "slippage": 0.05,
    },
}

HORIZON_TRADING_DAYS: dict[str, int] = {
    "intraday": 0,
    "swing": 5,
    "position": 21,
}

# Calendar-day buffer used to decide whether a window has plausibly closed.
# 21 trading days ≈ 31 calendar days; add a 5-day safety margin.
_WINDOW_CALENDAR_BUFFER: dict[str, int] = {
    "intraday": 1,
    "swing": 10,
    "position": 35,
}


def compute_round_trip_cost(horizon: str) -> float:
    """Return total round-trip transaction cost as a fraction.

    Brokerage is 0.03% per side uncapped (order size unknown).
    GST applies to (brokerage + exchange charge) per side.
    STT applies to the sell side only.
    Stamp duty applies to the buy side only.
    Slippage (market impact) is charged per side.
    """
    model = COST_MODEL["intraday"] if horizon == "intraday" else COST_MODEL["delivery"]

    b = model["brokerage"]
    stt = model["stt_sell"]
    exc = model["exchange"]
    gst_rate = model["gst_on_brokerage_and_exchange"]
    sebi = model["sebi"]
    stamp = model["stamp_buy"]
    slip = model["slippage"]

    gst_per_side = (b + exc) * gst_rate

    buy_side = b + exc + gst_per_side + sebi + stamp + slip
    sell_side = b + stt + exc + gst_per_side + sebi + slip

    return (buy_side + sell_side) / 100.0


def _date_str(dt: datetime | date) -> str:
    return dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)


def get_entry_price(symbol: str, as_of_date: str) -> tuple[float, str] | None:
    """Fetch the open price of the first trading day AFTER as_of_date.

    Returns (price, ISO-datetime-string) or None on failure.
    Fetches a 5-trading-day window starting the calendar day after as_of_date
    and takes the first available row's Open.
    """
    try:
        start = (datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        end = (datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d")
        if df.empty:
            log.warning("scorer.get_entry_price: no data", symbol=symbol, start=start)
            return None
        first_row = df.iloc[0]
        entry_dt = df.index[0]
        # Normalise to timezone-aware ISO string
        if hasattr(entry_dt, "tzinfo") and entry_dt.tzinfo is not None:
            dt_str = entry_dt.isoformat()
        else:
            dt_str = entry_dt.strftime("%Y-%m-%dT09:15:00+05:30")  # NSE open approx
        return float(first_row["Open"]), dt_str
    except Exception as exc:
        log.warning("scorer.get_entry_price: error", symbol=symbol, error=str(exc))
        return None


def get_exit_price(symbol: str, entry_date: str, horizon: str) -> tuple[float, str] | None:
    """Fetch the exit price for the given horizon window.

    entry_date: "YYYY-MM-DD" of the entry trading day (NOT as_of_date).
    - intraday: Close of the entry day (index 0).
    - swing:    Close of the 5th trading day after entry (index 5).
    - position: Close of the 21st trading day after entry (index 21).

    Returns (price, ISO-datetime-string) or None if the window has not yet
    closed (not enough rows returned by yfinance).
    """
    n_days = HORIZON_TRADING_DAYS[horizon]
    required_rows = n_days + 1  # row 0 is entry day; row n_days is exit

    # Buffer: fetch enough calendar days to cover required trading days
    calendar_fetch = max(n_days * 2 + 5, 10)
    try:
        start = entry_date
        end = (datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=calendar_fetch)).strftime(
            "%Y-%m-%d"
        )
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d")
        if len(df) < required_rows:
            log.debug(
                "scorer.get_exit_price: window not yet closed",
                symbol=symbol,
                horizon=horizon,
                rows=len(df),
                required=required_rows,
            )
            return None
        exit_row = df.iloc[n_days]
        exit_dt = df.index[n_days]
        if hasattr(exit_dt, "tzinfo") and exit_dt.tzinfo is not None:
            dt_str = exit_dt.isoformat()
        else:
            dt_str = exit_dt.strftime("%Y-%m-%dT15:30:00+05:30")  # NSE close approx
        return float(exit_row["Close"]), dt_str
    except Exception as exc:
        log.warning("scorer.get_exit_price: error", symbol=symbol, horizon=horizon, error=str(exc))
        return None


def _get_benchmark_return(entry_date: str, exit_date: str) -> float:
    """Nifty 50 close-to-close return from entry_date to exit_date.

    For intraday (entry_date == exit_date) returns open-to-close of that day.
    Returns 0.0 on any failure so benchmark absence doesn't crash scoring.
    """
    try:
        ticker = get_nifty50_ticker()
        end = (datetime.strptime(exit_date, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
        df = yf.Ticker(ticker).history(start=entry_date, end=end, interval="1d")
        if df.empty:
            return 0.0
        if entry_date == exit_date:
            # intraday: open-to-close
            entry_price = float(df.iloc[0]["Open"])
            exit_price = float(df.iloc[0]["Close"])
        else:
            entry_price = float(df.iloc[0]["Close"])
            # Find row matching exit_date
            exit_rows = df[df.index.strftime("%Y-%m-%d") == exit_date]  # type: ignore[attr-defined]
            if exit_rows.empty:
                exit_price = float(df.iloc[-1]["Close"])
            else:
                exit_price = float(exit_rows.iloc[0]["Close"])
        if entry_price == 0:
            return 0.0
        return (exit_price - entry_price) / entry_price
    except Exception as exc:
        log.warning("scorer._get_benchmark_return: error", error=str(exc))
        return 0.0


def score_pick(
    pick: PickItem,
    run_id: str,
    as_of_date: str,
    horizon: str,
) -> OutcomeRecord | None:
    """Score a single pick for one horizon window.

    Returns None if the exit window has not yet closed (get_exit_price
    returns fewer rows than required). Direction: for 'short', gross
    return is negated (profits when price falls).
    """
    entry = get_entry_price(pick.symbol, as_of_date)
    if entry is None:
        return None
    entry_price, entry_time = entry

    entry_date = entry_time[:10]  # "YYYY-MM-DD"
    exit_result = get_exit_price(pick.symbol, entry_date, horizon)
    if exit_result is None:
        return None
    exit_price, exit_time = exit_result

    exit_date = exit_time[:10]

    if entry_price == 0:
        log.warning("scorer.score_pick: entry_price is 0", symbol=pick.symbol)
        return None

    raw_return = (exit_price - entry_price) / entry_price
    gross_return = -raw_return if pick.direction == "short" else raw_return

    costs = compute_round_trip_cost(horizon)
    net_return = gross_return - costs
    benchmark_return = _get_benchmark_return(entry_date, exit_date)
    excess_return = net_return - benchmark_return

    return OutcomeRecord(
        outcome_id=str(uuid.uuid4()),
        run_id=run_id,
        symbol=pick.symbol,
        horizon=horizon,  # type: ignore[arg-type]
        entry_price=entry_price,
        entry_time=entry_time,
        exit_price=exit_price,
        exit_time=exit_time,
        gross_return=gross_return,
        costs=costs,
        net_return=net_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
    )


def score_run(pick_record: PickRecord, horizon: str) -> list[OutcomeRecord]:
    """Score all picks in a PickRecord for one horizon.

    Symbols that fail (yfinance error, window not closed) are skipped and
    logged. An empty list means nothing could be scored yet.
    """
    outcomes: list[OutcomeRecord] = []
    for pick in pick_record.picks:
        try:
            outcome = score_pick(pick, pick_record.run_id, pick_record.as_of_date, horizon)
            if outcome is not None:
                outcomes.append(outcome)
        except Exception as exc:
            log.warning(
                "scorer.score_run: skipping symbol",
                symbol=pick.symbol,
                horizon=horizon,
                error=str(exc),
            )
    return outcomes
