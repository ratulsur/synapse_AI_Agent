"""Universe definitions for the stock-picker eval harness.

All symbols carry the .NS suffix for NSE listings on Yahoo Finance.
Lists are point-in-time snapshots; once written to a UniverseSnapshot
the constituents are frozen for that run (survivorship-bias prevention).

Owner: Ratul Sur
"""

from __future__ import annotations

import uuid
from datetime import date

from evals.stock_picker.models import UniverseSnapshot

NIFTY50_SYMBOLS: list[str] = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "HINDUNILVR.NS",
    "ICICIBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "BAJFINANCE.NS", "BHARTIARTL.NS",
    "ASIANPAINT.NS", "MARUTI.NS", "HCLTECH.NS", "LTIM.NS", "SUNPHARMA.NS",
    "AXISBANK.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS", "ONGC.NS",
    "NESTLEIND.NS", "POWERGRID.NS", "NTPC.NS", "TATAMOTORS.NS", "JSWSTEEL.NS",
    "TECHM.NS", "INDUSINDBK.NS", "COALINDIA.NS", "HINDALCO.NS", "TATASTEEL.NS",
    "CIPLA.NS", "DIVISLAB.NS", "DRREDDY.NS", "BAJAJFINSV.NS", "BAJAJ-AUTO.NS",
    "BPCL.NS", "EICHERMOT.NS", "GRASIM.NS", "HEROMOTOCO.NS", "IOC.NS",
    "LT.NS", "M&M.NS", "SBILIFE.NS", "HDFCLIFE.NS", "APOLLOHOSP.NS",
    "BRITANNIA.NS", "ADANIENT.NS", "ADANIPORTS.NS", "TATACONSUM.NS", "UPL.NS",
]

# F&O-eligible names: all Nifty 50 plus the most liquid large-cap derivatives.
# Used when --universe NSE_FO is requested (allows short picks).
NSE_FO_SYMBOLS: list[str] = NIFTY50_SYMBOLS + [
    "ZOMATO.NS", "DMART.NS", "IRCTC.NS",
    "PFC.NS", "RECLTD.NS", "CANBK.NS", "BANKBARODA.NS", "PNB.NS",
    "MUTHOOTFIN.NS", "CHOLAFIN.NS",
    "PIDILITIND.NS",
    "TORNTPHARM.NS", "AUROPHARMA.NS", "LUPIN.NS",
    "TRENT.NS", "DABUR.NS", "MARICO.NS", "GODREJCP.NS",
    "SIEMENS.NS", "ABB.NS", "BHEL.NS", "BEL.NS", "HAL.NS",
    "SAIL.NS", "NMDC.NS",
    "GODREJPROP.NS", "DLF.NS",
    "INDIGO.NS",
    "TATAPOWER.NS", "ADANIGREEN.NS",
    "MPHASIS.NS", "COFORGE.NS", "LTTS.NS", "PERSISTENT.NS", "KPIT.NS",
]

NIFTY500_SYMBOLS: list[str] = NIFTY50_SYMBOLS + [
    "ZOMATO.NS", "NYKAA.NS", "PAYTM.NS", "DMART.NS", "IRCTC.NS",
    "PFC.NS", "RECLTD.NS", "CANBK.NS", "BANKBARODA.NS", "PNB.NS",
    "MUTHOOTFIN.NS", "CHOLAFIN.NS", "MANAPPURAM.NS", "BAJAJHFL.NS",
    "PIDILITIND.NS", "BERGEPAINT.NS", "KANSAINER.NS",
    "TORNTPHARM.NS", "AUROPHARMA.NS", "BIOCON.NS", "LUPIN.NS", "IPCALAB.NS",
    "TRENT.NS", "DABUR.NS", "MARICO.NS", "GODREJCP.NS", "EMAMILTD.NS",
    "MCDOWELL-N.NS", "RADICO.NS",
    "SIEMENS.NS", "ABB.NS", "BHEL.NS", "BEL.NS", "HAL.NS",
    "SAIL.NS", "NMDC.NS", "NATIONALUM.NS",
    "GODREJPROP.NS", "DLF.NS", "PRESTIGE.NS", "OBEROIRLTY.NS",
    "INDIGO.NS", "SPICEJET.NS",
    "ZEEL.NS", "PVR.NS", "INOXLEISUR.NS",
    "TATAPOWER.NS", "ADANIGREEN.NS", "TORNTPOWER.NS", "CESC.NS",
    "MPHASIS.NS", "COFORGE.NS", "LTTS.NS", "PERSISTENT.NS", "KPIT.NS",
    "DELHIVERY.NS", "CARTRADE.NS",
]

_UNIVERSE_MAP: dict[str, list[str]] = {
    "NIFTY50": NIFTY50_SYMBOLS,
    "NIFTY500": NIFTY500_SYMBOLS,
    "NSE_FO": NSE_FO_SYMBOLS,
}


def get_universe(name: str = "NIFTY500", date: str | None = None) -> UniverseSnapshot:
    """Return a frozen UniverseSnapshot for the named universe.

    date defaults to today's ISO date. Passing an explicit date allows
    reproducible backtest snapshots — the symbol list is still the
    hardcoded version at code time; historical constituent data is not
    fetched from an external source.
    """
    symbols = _UNIVERSE_MAP.get(name.upper())
    if symbols is None:
        raise ValueError(f"Unknown universe '{name}'. Valid: {list(_UNIVERSE_MAP)}")

    snap_date = date or str(__import__("datetime").date.today())
    return UniverseSnapshot(
        snapshot_id=str(uuid.uuid4()),
        date=snap_date,
        universe_name=name.upper(),
        symbols=list(symbols),
    )


def get_nifty50_ticker() -> str:
    """Yahoo Finance ticker for the Nifty 50 benchmark index."""
    return "^NSEI"
