"""Pydantic models for the stock-picker eval harness.

All records are immutable after creation. PickRecord carries a SHA256 hash
of its canonical JSON so the append-only ledger can detect tampering.

Owner: Ratul Sur
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel


class PickItem(BaseModel):
    symbol: str
    direction: Literal["long", "short"] = "long"
    confidence: float        # [0, 1]
    regime_label: str
    rationale: str


class PickRecord(BaseModel):
    run_id: str              # UUID4
    timestamp_utc: str       # ISO datetime
    mode: Literal["forward", "backtest"]
    as_of_date: str          # ISO date "YYYY-MM-DD"
    universe_snapshot_id: str
    model_id: str
    model_cutoff_date: str   # ISO date
    entry_rule: str          # always "next_open"
    k: int
    picks: list[PickItem]
    record_hash: str         # SHA256 of canonical JSON (excluding this field)


class OutcomeRecord(BaseModel):
    outcome_id: str          # UUID4
    run_id: str
    symbol: str
    horizon: Literal["intraday", "swing", "position"]
    entry_price: float
    entry_time: str          # ISO datetime
    exit_price: float
    exit_time: str           # ISO datetime
    gross_return: float      # direction-adjusted: (exit-entry)/entry, negated for short
    costs: float             # round-trip cost as fraction e.g. 0.002
    net_return: float        # gross - costs
    benchmark_return: float  # Nifty 50 return over same window
    excess_return: float     # net_return - benchmark_return


class RandomBaselineRecord(BaseModel):
    run_id: str
    horizon: str
    n_baskets: int
    mean_return: float
    std_return: float
    basket_returns: list[float]  # all M raw returns


class UniverseSnapshot(BaseModel):
    snapshot_id: str
    date: str
    universe_name: str
    symbols: list[str]


def hash_record(record: PickRecord) -> str:
    """SHA256 of the record JSON with record_hash set to empty string.

    sort_keys=True guarantees identical output regardless of dict insertion
    order so the hash is stable across Python versions and platforms.
    """
    d = record.model_dump()
    d["record_hash"] = ""
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
