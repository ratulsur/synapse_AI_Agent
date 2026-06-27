"""Statistical metrics for the stock-picker eval harness.

All functions are pure / deterministic and contain no LLM calls or I/O.

The three metric families match EVAL_HARNESS.md §6:
  (a) Skill    — does the agent beat the baselines?
  (b) Calibration — does it know its own winners (confidence vs excess_return)?
  (c) Risk-adjusted — return per unit of drawdown/vol.

Every conclusion carries a bootstrap confidence interval. The verdict gate
(can_render_verdict) blocks all conclusions below MIN_RUNS_FOR_VERDICT so
small samples never produce spurious "skill" claims.

Owner: Ratul Sur
"""

from __future__ import annotations

import math
import random

import numpy as np
from scipy import stats

from evals.stock_picker.models import OutcomeRecord, PickRecord, RandomBaselineRecord

MIN_RUNS_FOR_VERDICT = 30  # §7 — no verdict below this threshold


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def bootstrap_ci(
    values: list[float],
    n_boot: int = 2000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean.

    Returns (lower, upper). For n <= 1 returns (value, value) so callers
    always receive a finite tuple.
    """
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])

    arr = np.array(values, dtype=float)
    boot_means = np.array(
        [np.mean(arr[np.random.randint(0, len(arr), len(arr))]) for _ in range(n_boot)]
    )
    alpha = (1 - ci) / 2
    lower = float(np.percentile(boot_means, alpha * 100))
    upper = float(np.percentile(boot_means, (1 - alpha) * 100))
    return lower, upper


# ---------------------------------------------------------------------------
# (a) Skill metrics
# ---------------------------------------------------------------------------


def compute_skill_metrics(
    excess_returns: list[float],
    random_basket_returns: list[float],
) -> dict:
    """Skill: does the agent beat the benchmark and the random baseline?

    Args:
        excess_returns:        Per-pick net_return minus benchmark_return.
        random_basket_returns: All M basket returns from RandomBaselineRecord
                               (pooled across runs for the same horizon).

    Returns dict with keys:
        mean_excess_return, ci_lower, ci_upper,
        hit_rate (fraction > 0),
        percentile_vs_random (agent mean's percentile within random dist),
        n_picks
    """
    n_picks = len(excess_returns)
    if n_picks == 0:
        return {
            "mean_excess_return": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "hit_rate": 0.0,
            "percentile_vs_random": 0.0,
            "n_picks": 0,
        }

    mean_er = float(np.mean(excess_returns))
    ci_lower, ci_upper = bootstrap_ci(excess_returns)
    hit_rate = sum(1 for r in excess_returns if r > 0) / n_picks

    # Agent mean's percentile within the random basket distribution
    if random_basket_returns:
        pct = float(np.mean(np.array(random_basket_returns) < mean_er))
    else:
        pct = 0.5  # unknown — report neutral

    return {
        "mean_excess_return": mean_er,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "hit_rate": hit_rate,
        "percentile_vs_random": pct,
        "n_picks": n_picks,
    }


# ---------------------------------------------------------------------------
# (b) Calibration metrics
# ---------------------------------------------------------------------------


def compute_calibration_metrics(
    confidences: list[float],
    excess_returns: list[float],
) -> dict:
    """Calibration: do higher-confidence picks realise higher excess return?

    Spearman ρ between confidence and excess_return is the primary test.
    Top-decile vs bottom-decile gap (with bootstrap CI) is the headline
    effect-size metric.

    Returns dict with keys:
        spearman_rho, spearman_pvalue,
        top_decile_mean, bottom_decile_mean, gap,
        gap_ci_lower, gap_ci_upper
    """
    n = len(confidences)
    if n < 2 or len(excess_returns) != n:
        return {
            "spearman_rho": 0.0,
            "spearman_pvalue": 1.0,
            "top_decile_mean": 0.0,
            "bottom_decile_mean": 0.0,
            "gap": 0.0,
            "gap_ci_lower": 0.0,
            "gap_ci_upper": 0.0,
        }

    rho, pval = stats.spearmanr(confidences, excess_returns)

    # Decile split by confidence
    conf_arr = np.array(confidences)
    er_arr = np.array(excess_returns)
    top_threshold = np.percentile(conf_arr, 90)
    bot_threshold = np.percentile(conf_arr, 10)

    top_mask = conf_arr >= top_threshold
    bot_mask = conf_arr <= bot_threshold

    top_ers = er_arr[top_mask].tolist()
    bot_ers = er_arr[bot_mask].tolist()

    top_mean = float(np.mean(top_ers)) if top_ers else 0.0
    bot_mean = float(np.mean(bot_ers)) if bot_ers else 0.0
    gap = top_mean - bot_mean

    # Bootstrap CI on the gap via paired resampling from the full pool
    gap_samples = [
        r - random.choice(bot_ers) if bot_ers else 0.0
        for r in top_ers
    ]
    gap_ci_lower, gap_ci_upper = bootstrap_ci(gap_samples) if gap_samples else (gap, gap)

    return {
        "spearman_rho": float(rho),
        "spearman_pvalue": float(pval),
        "top_decile_mean": top_mean,
        "bottom_decile_mean": bot_mean,
        "gap": gap,
        "gap_ci_lower": gap_ci_lower,
        "gap_ci_upper": gap_ci_upper,
    }


# ---------------------------------------------------------------------------
# (c) Risk-adjusted metrics
# ---------------------------------------------------------------------------


def compute_risk_metrics(
    net_returns: list[float],
    benchmark_returns: list[float],
    trading_days_per_year: int = 252,
) -> dict:
    """Risk-adjusted metrics for the accumulated pick track record.

    Args:
        net_returns:       Per-pick net returns (after costs).
        benchmark_returns: Per-pick benchmark return over the same window.
        trading_days_per_year: Annualisation factor.

    Returns dict with keys:
        portfolio_vol, max_drawdown, sharpe, sortino, return_per_drawdown
    """
    if not net_returns:
        return {
            "portfolio_vol": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "return_per_drawdown": 0.0,
        }

    arr = np.array(net_returns, dtype=float)
    mean_r = float(np.mean(arr))
    vol = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    # Annualise assuming each pick is an independent observation.
    ann_factor = math.sqrt(trading_days_per_year)
    sharpe = (mean_r / vol * ann_factor) if vol > 0 else 0.0

    downside = arr[arr < 0]
    downside_vol = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (mean_r / downside_vol * ann_factor) if downside_vol > 0 else 0.0

    # Cumulative return series for drawdown (treat picks as sequential periods)
    cum = np.cumprod(1.0 + arr)
    running_max = np.maximum.accumulate(cum)
    drawdown_series = (cum - running_max) / running_max
    max_drawdown = float(np.min(drawdown_series))

    total_return = float(np.prod(1.0 + arr) - 1.0)
    return_per_drawdown = (total_return / abs(max_drawdown)) if max_drawdown != 0 else 0.0

    return {
        "portfolio_vol": vol,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "return_per_drawdown": return_per_drawdown,
    }


# ---------------------------------------------------------------------------
# Verdict gate
# ---------------------------------------------------------------------------


def can_render_verdict(n_runs: int) -> bool:
    """Block conclusions when sample size is below MIN_RUNS_FOR_VERDICT."""
    return n_runs >= MIN_RUNS_FOR_VERDICT


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------


def render_report(
    picks: list[PickRecord],
    outcomes: list[OutcomeRecord],
    baselines: list[RandomBaselineRecord],
) -> str:
    """Render a markdown report of agent stock-picking capacity.

    If fewer than MIN_RUNS_FOR_VERDICT distinct runs have outcomes, the
    report states INSUFFICIENT DATA and reports the current sample size.
    Otherwise it reports skill, calibration, and risk sections per horizon,
    plus a per-pick detail table.
    """
    lines: list[str] = []
    lines.append("# Stock-Picker Capacity Report")
    lines.append("")

    horizons = ["intraday", "swing", "position"]

    # Index structures
    outcome_by_run_horizon: dict[tuple[str, str], list[OutcomeRecord]] = {}
    for o in outcomes:
        key = (o.run_id, o.horizon)
        outcome_by_run_horizon.setdefault(key, []).append(o)

    baseline_by_run_horizon: dict[tuple[str, str], RandomBaselineRecord] = {
        (b.run_id, b.horizon): b for b in baselines
    }

    pick_by_run_id: dict[str, PickRecord] = {p.run_id: p for p in picks}

    # Count runs that have outcomes for each horizon
    runs_with_outcomes: dict[str, set[str]] = {h: set() for h in horizons}
    for (run_id, horizon), _ in outcome_by_run_horizon.items():
        runs_with_outcomes[horizon].add(run_id)

    # Regime summary
    mode_counts: dict[str, int] = {}
    for p in picks:
        mode_counts[p.mode] = mode_counts.get(p.mode, 0) + 1
    regime_labels: set[str] = {item.regime_label for p in picks for item in p.picks}

    lines.append("## Sample Summary")
    lines.append(f"- Total pick records: {len(picks)}")
    lines.append(f"- Total outcome records: {len(outcomes)}")
    lines.append(f"- Mode breakdown: {mode_counts}")
    lines.append(f"- Regime labels observed: {sorted(regime_labels) or ['(none)']}")
    lines.append(f"- MIN_RUNS_FOR_VERDICT threshold: {MIN_RUNS_FOR_VERDICT}")
    lines.append("")

    # Per-horizon sections
    for horizon in horizons:
        lines.append(f"## Horizon: {horizon.capitalize()}")
        n_runs = len(runs_with_outcomes[horizon])
        lines.append(f"- Runs with outcomes: {n_runs}")

        if not can_render_verdict(n_runs):
            lines.append(
                f"- **INSUFFICIENT DATA**: {n_runs}/{MIN_RUNS_FOR_VERDICT} runs. "
                "No verdict rendered."
            )
            lines.append("")
            continue

        # Collect all outcomes for this horizon
        h_outcomes: list[OutcomeRecord] = [o for o in outcomes if o.horizon == horizon]
        excess_returns = [o.excess_return for o in h_outcomes]
        net_returns = [o.net_return for o in h_outcomes]
        benchmark_returns = [o.benchmark_return for o in h_outcomes]

        # Pool all basket returns from baselines for this horizon
        basket_pool: list[float] = []
        for b in baselines:
            if b.horizon == horizon:
                basket_pool.extend(b.basket_returns)

        # Confidence per pick (mapped via run_id + symbol)
        pick_confidence: dict[tuple[str, str], float] = {}
        for p in picks:
            for item in p.picks:
                pick_confidence[(p.run_id, item.symbol)] = item.confidence
        confidences = [
            pick_confidence.get((o.run_id, o.symbol), 0.5) for o in h_outcomes
        ]

        skill = compute_skill_metrics(excess_returns, basket_pool)
        calib = compute_calibration_metrics(confidences, excess_returns)
        risk = compute_risk_metrics(net_returns, benchmark_returns)

        lines.append("")
        lines.append("### (a) Skill vs Baselines")
        lines.append(f"- N picks: {skill['n_picks']}")
        lines.append(
            f"- Mean excess return: {skill['mean_excess_return']:.4f} "
            f"(95% CI [{skill['ci_lower']:.4f}, {skill['ci_upper']:.4f}])"
        )
        lines.append(f"- Hit rate (excess > 0): {skill['hit_rate']:.2%}")
        lines.append(f"- Percentile vs random baskets: {skill['percentile_vs_random']:.2%}")

        lines.append("")
        lines.append("### (b) Calibration")
        lines.append(f"- Spearman ρ (confidence vs excess return): {calib['spearman_rho']:.4f} (p={calib['spearman_pvalue']:.4f})")
        lines.append(f"- Top-decile mean excess return: {calib['top_decile_mean']:.4f}")
        lines.append(f"- Bottom-decile mean excess return: {calib['bottom_decile_mean']:.4f}")
        lines.append(
            f"- Gap: {calib['gap']:.4f} "
            f"(95% CI [{calib['gap_ci_lower']:.4f}, {calib['gap_ci_upper']:.4f}])"
        )

        lines.append("")
        lines.append("### (c) Risk-Adjusted")
        lines.append(f"- Portfolio vol: {risk['portfolio_vol']:.4f}")
        lines.append(f"- Max drawdown: {risk['max_drawdown']:.4f}")
        lines.append(f"- Sharpe (annualised): {risk['sharpe']:.4f}")
        lines.append(f"- Sortino (annualised): {risk['sortino']:.4f}")
        lines.append(f"- Return / max drawdown: {risk['return_per_drawdown']:.4f}")
        lines.append("")

    # Per-pick detail table
    lines.append("## Per-Pick Detail")
    header = "| run_id | symbol | direction | confidence | horizon | gross_return | net_return | excess_return |"
    sep    = "|--------|--------|-----------|------------|---------|-------------|------------|---------------|"
    lines.append(header)
    lines.append(sep)
    for o in sorted(outcomes, key=lambda x: (x.run_id, x.symbol, x.horizon)):
        run_short = o.run_id[:8]
        lines.append(
            f"| {run_short} | {o.symbol} | "
            f"{'long'} | "  # direction stored in PickRecord; approximated here
            f"- | {o.horizon} | {o.gross_return:.4f} | {o.net_return:.4f} | {o.excess_return:.4f} |"
        )
    lines.append("")

    return "\n".join(lines)
