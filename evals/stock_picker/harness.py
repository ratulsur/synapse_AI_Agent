"""CLI entry point for the stock-picker eval harness.

Usage
-----
python -m evals.stock_picker.harness pick   [options]
python -m evals.stock_picker.harness score  [options]
python -m evals.stock_picker.harness report [options]

This package is STANDALONE — it does not invoke the LangGraph pipeline.
The equity-research-analyst agent is called directly for picks.

Owner: Ratul Sur
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from log import GLOBAL_LOGGER as log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_CUTOFF_DATE = "2025-08-01"   # knowledge cutoff for backtest honesty check
HORIZONS = ["intraday", "swing", "position"]

_LLM_PROVIDER_MODEL_MAP = {
    "openai": "gpt-4o",
    "groq": "llama-3.3-70b-versatile",
    "google": "gemini-1.5-pro",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _get_model_id() -> str:
    import os
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    return _LLM_PROVIDER_MODEL_MAP.get(provider, provider)


def _build_ohlcv_context(
    symbols: list[str],
    sample_size: int = 50,
) -> dict[str, dict]:
    """Fetch 30-day OHLCV summary for a sample of universe symbols.

    Returns {symbol: {last_close, pct_change_30d, avg_volume}}.
    Symbols that fail are silently skipped.
    """
    import yfinance as yf

    sample = symbols[:sample_size]
    context: dict[str, dict] = {}

    from datetime import date as _date
    end = _date.today().isoformat()
    start = (_date.today() - timedelta(days=45)).isoformat()

    for sym in sample:
        try:
            df = yf.Ticker(sym).history(start=start, end=end, interval="1d")
            if df.empty or len(df) < 2:
                continue
            last_close = float(df["Close"].iloc[-1])
            first_close = float(df["Close"].iloc[0])
            pct_change_30d = (last_close - first_close) / first_close if first_close else 0.0
            avg_volume = float(df["Volume"].mean())
            context[sym] = {
                "last_close": last_close,
                "pct_change_30d": pct_change_30d,
                "avg_volume": avg_volume,
            }
        except Exception as exc:
            log.debug("harness._build_ohlcv_context: skipping", symbol=sym, error=str(exc))

    return context


def _print_picks_table(picks) -> None:
    print(f"\n{'Symbol':<20} {'Dir':<6} {'Conf':>6} {'Regime':<12} {'Rationale'}")
    print("-" * 80)
    for p in picks:
        rationale_short = p.rationale[:45] + "..." if len(p.rationale) > 45 else p.rationale
        print(f"{p.symbol:<20} {p.direction:<6} {p.confidence:>6.2f} {p.regime_label:<12} {rationale_short}")


# ---------------------------------------------------------------------------
# Subcommand: pick
# ---------------------------------------------------------------------------


def cmd_pick(args: argparse.Namespace) -> int:
    from evals.stock_picker.ledger import Ledger
    from evals.stock_picker.models import PickRecord, hash_record
    from evals.stock_picker.universe import get_universe

    mode = args.mode
    as_of_date = args.as_of_date or _today()
    k = args.k
    universe_name = args.universe

    # Backtest honesty check — enforced mechanically, not by trust
    if mode == "backtest" and as_of_date <= MODEL_CUTOFF_DATE:
        print(
            f"ERROR: backtest as_of_date '{as_of_date}' is on or before the model "
            f"cutoff date '{MODEL_CUTOFF_DATE}'. The model has seen this period in "
            "training — backtest would be contaminated. Aborting.",
            file=sys.stderr,
        )
        return 1

    if mode == "backtest" and as_of_date >= _today():
        print(
            f"ERROR: backtest as_of_date '{as_of_date}' is today or in the future. "
            "Backtest requires an as_of_date in the past so outcomes are already known.",
            file=sys.stderr,
        )
        return 1

    print(f"[stock_picker] mode={mode}, as_of_date={as_of_date}, k={k}, universe={universe_name}")

    # Universe snapshot
    universe_snap = get_universe(universe_name, as_of_date)
    symbols = universe_snap.symbols
    print(f"[stock_picker] Universe: {len(symbols)} symbols")

    # OHLCV context
    print("[stock_picker] Fetching OHLCV context (up to 50 symbols)...")
    sample_size = min(50, len(symbols))
    context_data = _build_ohlcv_context(symbols, sample_size=sample_size)
    print(f"[stock_picker] Context fetched for {len(context_data)} symbols")

    # Agent call
    print(f"[stock_picker] Calling equity-research-analyst (k={k})...")
    try:
        from agents.equity_research_analyst import run_equity_research_analyst
        pick_items = run_equity_research_analyst(
            universe_symbols=symbols,
            context_data=context_data,
            k=k,
            mode=mode,
            as_of_date=as_of_date,
        )
    except (ImportError, NotImplementedError, AttributeError) as exc:
        log.warning("harness.cmd_pick: agent unavailable, using random fallback", error=str(exc))
        from evals.stock_picker.models import PickItem
        chosen = random.sample(symbols, min(k, len(symbols)))
        pick_items = [
            PickItem(
                symbol=sym,
                direction="long",
                confidence=0.5,
                regime_label="GENERIC",
                rationale="Agent unavailable — random fallback",
            )
            for sym in chosen
        ]

    # Enforce exactly K picks
    if len(pick_items) != k:
        print(
            f"ERROR: agent returned {len(pick_items)} picks but K={k}. Aborting.",
            file=sys.stderr,
        )
        return 1

    # Build and hash the PickRecord
    model_id = _get_model_id()
    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    record = PickRecord(
        run_id=run_id,
        timestamp_utc=timestamp,
        mode=mode,  # type: ignore[arg-type]
        as_of_date=as_of_date,
        universe_snapshot_id=universe_snap.snapshot_id,
        model_id=model_id,
        model_cutoff_date=MODEL_CUTOFF_DATE,
        entry_rule="next_open",
        k=k,
        picks=pick_items,
        record_hash="",  # placeholder; replaced below
    )
    record = record.model_copy(update={"record_hash": hash_record(record)})

    # Write to ledger
    ledger = Ledger(args.db)
    ledger.write_universe(universe_snap)
    ledger.write_pick(record)

    print(f"\n[stock_picker] Pick record written. run_id={run_id}")
    _print_picks_table(pick_items)
    return 0


# ---------------------------------------------------------------------------
# Subcommand: score
# ---------------------------------------------------------------------------


def cmd_score(args: argparse.Namespace) -> int:
    from evals.stock_picker.baselines import compute_random_baseline
    from evals.stock_picker.ledger import Ledger
    from evals.stock_picker.scorer import score_run

    ledger = Ledger(args.db)

    if args.run_id:
        pick = ledger.get_pick(args.run_id)
        if pick is None:
            print(f"ERROR: run_id '{args.run_id}' not found in ledger.", file=sys.stderr)
            return 1
        open_picks = [pick]
    else:
        open_picks = ledger.get_open_picks()

    if not open_picks:
        print("[stock_picker] No open picks to score.")
        return 0

    print(f"[stock_picker] Scoring {len(open_picks)} open pick record(s)...")
    scored_count = 0
    skipped_count = 0

    for pick in open_picks:
        print(f"\n  run_id={pick.run_id[:8]}... as_of_date={pick.as_of_date} k={pick.k}")

        # Score all 3 horizons
        horizon_outcomes = {}
        for horizon in HORIZONS:
            outcomes = score_run(pick, horizon)
            horizon_outcomes[horizon] = outcomes
            print(f"    {horizon}: {len(outcomes)}/{pick.k} picks scored")

        # Only write if the position horizon (longest window) has outcomes for all picks.
        # Partial scoring within a horizon is allowed; incomplete horizons are skipped.
        position_outcomes = horizon_outcomes.get("position", [])
        if not position_outcomes:
            print(f"    -> Position window not yet closed. Skipping run {pick.run_id[:8]}...")
            skipped_count += 1
            continue

        # Write outcomes and baselines for all available horizons
        for horizon, outcomes in horizon_outcomes.items():
            if not outcomes:
                continue
            # Skip horizons already written to maintain append-only invariant
            existing = ledger.get_outcomes(pick.run_id)
            existing_keys = {(o.run_id, o.symbol, o.horizon) for o in existing}

            for outcome in outcomes:
                key = (outcome.run_id, outcome.symbol, outcome.horizon)
                if key not in existing_keys:
                    try:
                        ledger.write_outcome(outcome)
                    except Exception as exc:
                        log.warning("harness.cmd_score: write_outcome failed", error=str(exc))

            # Baseline — compute once per (run, horizon); skip if already present
            if ledger.get_baseline(pick.run_id, horizon) is None and outcomes:
                try:
                    # Derive entry/exit dates from the scored outcomes
                    entry_date = outcomes[0].entry_time[:10]
                    exit_date = outcomes[0].exit_time[:10]
                    baseline = compute_random_baseline(
                        pick_record=pick,
                        horizon=horizon,
                        entry_date=entry_date,
                        exit_date=exit_date,
                        n_baskets=1000,
                    )
                    ledger.write_baseline(baseline)
                    print(
                        f"    baseline [{horizon}]: {baseline.n_baskets} baskets, "
                        f"mean={baseline.mean_return:.4f}"
                    )
                except Exception as exc:
                    log.warning(
                        "harness.cmd_score: compute_random_baseline failed",
                        run_id=pick.run_id,
                        horizon=horizon,
                        error=str(exc),
                    )

        scored_count += 1

    print(f"\n[stock_picker] Scored: {scored_count}, skipped (window open): {skipped_count}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: report
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    from evals.stock_picker.ledger import Ledger
    from evals.stock_picker.metrics import render_report

    ledger = Ledger(args.db)

    picks = ledger.get_all_picks()
    outcomes = ledger.get_all_outcomes()
    baselines = ledger.get_all_baselines()

    horizon_filter = args.horizon.lower() if args.horizon != "all" else None
    if horizon_filter:
        outcomes = [o for o in outcomes if o.horizon == horizon_filter]
        baselines = [b for b in baselines if b.horizon == horizon_filter]

    report = render_report(picks=picks, outcomes=outcomes, baselines=baselines)
    print(report)
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Stock-picker eval harness — pick / score / report"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- pick ---
    p_pick = sub.add_parser("pick", help="Run the equity-research-analyst and record picks.")
    p_pick.add_argument(
        "--mode", choices=["forward", "backtest"], default="forward",
        help="Experiment mode (default: forward).",
    )
    p_pick.add_argument(
        "--as-of-date", dest="as_of_date", default=None,
        help="YYYY-MM-DD snapshot date. Default: today (for forward). Required for backtest.",
    )
    p_pick.add_argument(
        "--k", type=int, default=10,
        help="Number of picks (default: 10).",
    )
    p_pick.add_argument(
        "--universe", default="NIFTY500", choices=["NIFTY500", "NSE_FO"],
        help="Universe to pick from (default: NIFTY500).",
    )
    p_pick.add_argument("--db", default=None, help="Path to ledger.db (optional).")

    # --- score ---
    p_score = sub.add_parser("score", help="Score open picks against real prices.")
    p_score.add_argument("--run-id", dest="run_id", default=None,
                         help="Score a specific run_id (default: all open picks).")
    p_score.add_argument("--db", default=None, help="Path to ledger.db (optional).")

    # --- report ---
    p_report = sub.add_parser("report", help="Render the markdown capacity report.")
    p_report.add_argument(
        "--horizon", default="all", choices=["intraday", "swing", "position", "all"],
        help="Filter to one horizon (default: all).",
    )
    p_report.add_argument("--db", default=None, help="Path to ledger.db (optional).")

    args = parser.parse_args()

    dispatch = {
        "pick": cmd_pick,
        "score": cmd_score,
        "report": cmd_report,
    }
    fn = dispatch[args.command]
    sys.exit(fn(args))


if __name__ == "__main__":
    _cli()
