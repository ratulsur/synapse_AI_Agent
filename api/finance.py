"""Finance API — live OHLCV candlestick quote endpoint.

GET /finance/quote/{ticker}?period=1mo&interval=1d
    Returns structured candlestick bars + summary stats for client-side charting.
    Auth: JWT bearer required.

Owner: Ratul Sur
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.security import get_current_user
from db.models import User
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config

router = APIRouter(prefix="/finance", tags=["finance"])

_VALID_PERIODS   = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}
_VALID_INTERVALS = {"1m", "5m", "15m", "1h", "1d", "1wk", "1mo"}
_INTRADAY        = {"1m", "5m", "15m", "1h"}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OHLCVBar(BaseModel):
    time:   str    # "YYYY-MM-DD" for daily/weekly; unix-seconds string for intraday
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int


class QuoteSummary(BaseModel):
    last_close:  float
    pct_change:  float          # percentage, e.g. 2.35 means +2.35 %
    trend:       str            # "uptrend" | "downtrend" | "sideways"
    period_high: float
    period_low:  float
    sma20:       float | None
    sma50:       float | None
    avg_volume:  float
    n_bars:      int


class QuoteResponse(BaseModel):
    ticker:   str
    period:   str
    interval: str
    bars:     list[OHLCVBar]
    summary:  QuoteSummary


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/quote/{ticker}", response_model=QuoteResponse)
async def get_quote(
    ticker:   str,
    period:   str = Query(default="1mo", description="yfinance period string"),
    interval: str = Query(default="1d",  description="yfinance interval string"),
    user: User = Depends(get_current_user),
) -> QuoteResponse:
    """Fetch live OHLCV data for a single ticker via Yahoo Finance."""
    ticker = ticker.upper().strip()

    cfg = load_config()
    fc  = cfg.get("tools", {}).get("finance", {})

    if period   not in _VALID_PERIODS:   period   = str(fc.get("default_period",   "1mo"))
    if interval not in _VALID_INTERVALS: interval = str(fc.get("default_interval", "1d"))
    timeout = int(fc.get("timeout", 15))

    try:
        import yfinance as yf  # type: ignore[import]
    except ImportError:
        raise HTTPException(status_code=503, detail="yfinance is not available on this server")

    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, timeout=timeout)
    except Exception as exc:
        log.warning("finance_api: yfinance fetch failed", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Data fetch failed for {ticker!r}: {exc}")

    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No market data found for {ticker!r}")

    is_intraday = interval in _INTRADAY
    bars: list[OHLCVBar] = []
    for ts, row in df.iterrows():
        try:
            time_val = str(int(ts.timestamp())) if is_intraday else ts.strftime("%Y-%m-%d")
            bars.append(OHLCVBar(
                time=time_val,
                open=round(float(row["Open"]),   4),
                high=round(float(row["High"]),   4),
                low=round(float(row["Low"]),    4),
                close=round(float(row["Close"]), 4),
                volume=int(row["Volume"]),
            ))
        except Exception:
            continue

    if not bars:
        raise HTTPException(status_code=404, detail=f"No valid bars parsed for {ticker!r}")

    n     = len(df)
    close = df["Close"]
    f_open     = float(df["Open"].iloc[0])
    last_close = float(close.iloc[-1])
    pct        = (last_close - f_open) / f_open * 100 if f_open else 0.0
    trend      = "uptrend" if pct > 2 else ("downtrend" if pct < -2 else "sideways")
    sma20      = round(float(close.rolling(20).mean().iloc[-1]), 4) if n >= 20 else None
    sma50      = round(float(close.rolling(50).mean().iloc[-1]), 4) if n >= 50 else None

    summary = QuoteSummary(
        last_close=round(last_close, 4),
        pct_change=round(pct, 2),
        trend=trend,
        period_high=round(float(df["High"].max()), 4),
        period_low=round(float(df["Low"].min()),  4),
        sma20=sma20,
        sma50=sma50,
        avg_volume=round(float(df["Volume"].mean()), 0),
        n_bars=n,
    )

    log.info("finance_api: quote served", ticker=ticker, bars=len(bars), period=period)
    return QuoteResponse(ticker=ticker, period=period, interval=interval, bars=bars, summary=summary)
