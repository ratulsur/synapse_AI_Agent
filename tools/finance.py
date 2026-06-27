"""Yahoo Finance OHLCV tool — market data via yfinance (Finance domain).

Fetches OHLCV (Open/High/Low/Close/Volume) data for one or more tickers and
returns a structured text summary with price action, trend direction, moving
averages, volume statistics, and support/resistance levels.

Hit schema:
    {"title": str, "url": str, "content": str, "author": str, "score": float, "_tool": "finance"}

Owner: backend-developer
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config

# ---------------------------------------------------------------------------
# Valid parameter sets for coercion
# ---------------------------------------------------------------------------

_VALID_PERIODS: frozenset[str] = frozenset(
    {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}
)
_VALID_INTERVALS: frozenset[str] = frozenset(
    {"1m", "5m", "15m", "1h", "1d", "1wk", "1mo"}
)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class FinanceOHLCVInput(BaseModel):
    """Structured input for the finance_ohlcv tool."""

    ticker: str = Field(
        description=(
            "One stock symbol or a comma-separated list "
            "(e.g. 'AAPL' or 'AAPL,MSFT')."
        )
    )
    period: str = Field(
        default="1mo",
        description=(
            "yfinance period string: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max."
        ),
    )
    interval: str = Field(
        default="1d",
        description=(
            "yfinance interval string: 1m, 5m, 15m, 1h, 1d, 1wk, 1mo."
        ),
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool(args_schema=FinanceOHLCVInput)
def finance_ohlcv(ticker: str, period: str = "1mo", interval: str = "1d") -> str:
    """Fetch OHLCV price/volume data for one or more stock tickers via Yahoo Finance.

    Args:
        ticker:   One symbol or comma-separated list (e.g. 'AAPL' or 'AAPL,MSFT').
        period:   yfinance period string (1d,5d,1mo,3mo,6mo,1y,2y,5y,ytd,max).
        interval: yfinance interval string (1m,5m,15m,1h,1d,1wk,1mo).

    Returns:
        JSON string — list of hit dicts with keys:
        title, url, content, author, score, _tool.
        Returns ``"[]"`` on any error or when disabled so the graph does not crash.
    """
    try:
        cfg = load_config()
        finance_cfg: dict = cfg.get("tools", {}).get("finance", {})

        enabled: bool = bool(finance_cfg.get("enabled", True))
        default_period: str = str(finance_cfg.get("default_period", "1mo"))
        default_interval: str = str(finance_cfg.get("default_interval", "1d"))
        max_tickers: int = int(finance_cfg.get("max_tickers", 3))
        timeout: int = int(finance_cfg.get("timeout", 15))

        if not enabled:
            log.debug(
                "finance_ohlcv: disabled in config (tools.finance.enabled=false)"
            )
            return json.dumps([])

        # Coerce invalid period/interval to config defaults (never raise)
        if period not in _VALID_PERIODS:
            log.debug(
                "finance_ohlcv: invalid period, coercing to default",
                received=period,
                default=default_period,
            )
            period = default_period
        if interval not in _VALID_INTERVALS:
            log.debug(
                "finance_ohlcv: invalid interval, coercing to default",
                received=interval,
                default=default_interval,
            )
            interval = default_interval

        try:
            import yfinance as yf  # type: ignore[import]
        except ImportError:
            log.warning(
                "finance_ohlcv: yfinance package not installed; returning empty results"
            )
            return json.dumps([])

        # Parse and cap tickers
        raw_symbols = [t.strip().upper() for t in ticker.split(",") if t.strip()]
        symbols = raw_symbols[:max_tickers]

        log.info(
            "finance_ohlcv: fetching OHLCV",
            tickers=symbols,
            period=period,
            interval=interval,
        )

        hits: list[dict] = []
        for sym in symbols:
            try:
                ticker_obj = yf.Ticker(sym)
                df = ticker_obj.history(
                    period=period, interval=interval, timeout=timeout
                )

                if df is None or df.empty:
                    log.warning(
                        "finance_ohlcv: empty DataFrame (bad ticker or no data)",
                        ticker=sym,
                    )
                    continue

                content = _build_content(sym, period, interval, df)
                hits.append(
                    {
                        "title": f"{sym} — OHLCV (period={period}, interval={interval})",
                        "url": f"https://finance.yahoo.com/quote/{sym}",
                        "content": content,
                        "author": "Yahoo Finance via yfinance",
                        "score": 0.9,
                        "_tool": "finance",
                    }
                )

            except Exception as exc:  # noqa: BLE001 — skip bad tickers; don't crash
                log.warning(
                    "finance_ohlcv: failed for ticker",
                    ticker=sym,
                    error=str(exc),
                )
                continue

        if not hits:
            log.warning(
                "finance_ohlcv: no data returned for any ticker", tickers=symbols
            )
            return json.dumps([])

        log.info("finance_ohlcv: results", count=len(hits))
        return json.dumps(hits)

    except Exception as exc:  # noqa: BLE001 — never let tool failure crash the graph
        log.warning("finance_ohlcv: unexpected error", error=str(exc))
        return json.dumps([])


# ---------------------------------------------------------------------------
# Content builder
# ---------------------------------------------------------------------------

def _build_content(sym: str, period: str, interval: str, df) -> str:
    """Build the structured OHLCV text summary for one ticker's DataFrame."""
    n_bars: int = len(df)

    # Date range
    idx = df.index
    start_date: str = _fmt_date(idx[0])
    end_date: str = _fmt_date(idx[-1])
    last_date: str = end_date

    # Price statistics
    first_open: float = float(df["Open"].iloc[0])
    last_close: float = float(df["Close"].iloc[-1])
    pct_change: float = (
        (last_close - first_open) / first_open if first_open != 0.0 else 0.0
    )

    # Trend classification
    if pct_change > 0.02:
        trend = "uptrend"
    elif pct_change < -0.02:
        trend = "downtrend"
    else:
        trend = "sideways"

    # Window high / low with dates
    low_val: float = float(df["Low"].min())
    low_date: str = _fmt_date(df["Low"].idxmin())
    high_val: float = float(df["High"].max())
    high_date: str = _fmt_date(df["High"].idxmax())

    # Up / down day counts
    up_days: int = int((df["Close"] > df["Open"]).sum())
    down_days: int = int((df["Close"] < df["Open"]).sum())

    # Moving averages
    close_series = df["Close"]
    if n_bars >= 20:
        sma20_val: float = float(close_series.rolling(20).mean().iloc[-1])
        d20: float = (last_close - sma20_val) / sma20_val if sma20_val != 0.0 else 0.0
        above20: str = "above" if last_close >= sma20_val else "below"
        sma20_line = (
            f"Moving averages: close {last_close:.2f} vs SMA20 {sma20_val:.2f}"
            f" ({above20}, {d20:+.1%});"
        )
    else:
        sma20_line = "Moving averages: insufficient bars for SMA20;"

    if n_bars >= 50:
        sma50_val: float = float(close_series.rolling(50).mean().iloc[-1])
        d50: float = (
            (last_close - sma50_val) / sma50_val if sma50_val != 0.0 else 0.0
        )
        above50: str = "above" if last_close >= sma50_val else "below"
        sma50_line = (
            f"                 vs SMA50 {sma50_val:.2f} ({above50}, {d50:+.1%})."
        )
    else:
        sma50_line = "                 insufficient bars for SMA50."

    # Support / resistance (window extremes)
    support: float = low_val
    resistance: float = high_val

    # Volume statistics
    vol_series = df["Volume"]
    avg_vol: float = float(vol_series.mean())
    recent_vol: float = float(vol_series.iloc[-5:].mean())
    vol_delta: float = (
        (recent_vol - avg_vol) / avg_vol if avg_vol != 0.0 else 0.0
    )
    vol_trend: str = "rising" if vol_delta > 0 else "falling"
    peak_vol: float = float(vol_series.max())
    peak_vol_date: str = _fmt_date(vol_series.idxmax())

    lines = [
        f"{sym} — OHLCV summary",
        f"Window: period={period}, interval={interval}, {n_bars} bars, {start_date} → {end_date}",
        f"Data as of last close {last_date} (delayed/last available; not real-time intraday).",
        "",
        f"Price: open {first_open:.2f}, last close {last_close:.2f} ({pct_change:+.1%} over window).",
        f"Range: low {low_val:.2f} ({low_date}), high {high_val:.2f} ({high_date}).",
        f"Trend: {trend}; {up_days} up days / {down_days} down days.",
        sma20_line,
        sma50_line,
        f"Support / resistance: nearest support ~{support:.2f}, nearest resistance ~{resistance:.2f}.",
        f"Volume: window avg {avg_vol:,.0f}, last-5-bar avg {recent_vol:,.0f} ({vol_trend}, {vol_delta:+.0%});",
        f"        peak {peak_vol:,.0f} on {peak_vol_date}.",
    ]
    return "\n".join(lines)


def _fmt_date(ts) -> str:
    """Format a pandas Timestamp (or any object with strftime) as YYYY-MM-DD."""
    try:
        return ts.strftime("%Y-%m-%d")
    except AttributeError:
        return str(ts)[:10]
