"""SQLite append-only ledger for pick and outcome records.

The ledger is strictly INSERT-only — no UPDATE or DELETE is ever issued.
Records are stored as JSON blobs so the schema survives model evolution
without migrations; the record_hash on PickRecord catches any tampering.

Owner: Ratul Sur
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from evals.stock_picker.models import (
    OutcomeRecord,
    PickRecord,
    RandomBaselineRecord,
    UniverseSnapshot,
    hash_record,
)

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pick_records (
    run_id      TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcome_records (
    outcome_id  TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    horizon     TEXT NOT NULL,
    data        TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS baseline_records (
    run_id      TEXT NOT NULL,
    horizon     TEXT NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (run_id, horizon)
);

CREATE TABLE IF NOT EXISTS universe_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    data        TEXT NOT NULL
);
"""


class Ledger:
    """Thread-safe SQLite ledger wrapper.

    Each public method opens and closes its own connection so the instance
    can be shared across subcommands within the same process without
    connection lifecycle concerns.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Writes (INSERT only)
    # ------------------------------------------------------------------

    def write_pick(self, record: PickRecord) -> None:
        """INSERT a PickRecord. Raises sqlite3.IntegrityError on duplicate run_id."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pick_records (run_id, data, inserted_at) VALUES (?, ?, ?)",
                (record.run_id, record.model_dump_json(), self._now_iso()),
            )

    def write_outcome(self, record: OutcomeRecord) -> None:
        """INSERT an OutcomeRecord. Raises sqlite3.IntegrityError on duplicate outcome_id."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO outcome_records (outcome_id, run_id, symbol, horizon, data, inserted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.outcome_id,
                    record.run_id,
                    record.symbol,
                    record.horizon,
                    record.model_dump_json(),
                    self._now_iso(),
                ),
            )

    def write_baseline(self, record: RandomBaselineRecord) -> None:
        """INSERT a RandomBaselineRecord. Raises sqlite3.IntegrityError on duplicate (run_id, horizon)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO baseline_records (run_id, horizon, data) VALUES (?, ?, ?)",
                (record.run_id, record.horizon, record.model_dump_json()),
            )

    def write_universe(self, snap: UniverseSnapshot) -> None:
        """INSERT a UniverseSnapshot. Raises sqlite3.IntegrityError on duplicate snapshot_id."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO universe_snapshots (snapshot_id, data) VALUES (?, ?)",
                (snap.snapshot_id, snap.model_dump_json()),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_pick(self, run_id: str) -> PickRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM pick_records WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return PickRecord.model_validate_json(row["data"])

    def get_all_picks(self) -> list[PickRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM pick_records ORDER BY inserted_at"
            ).fetchall()
        return [PickRecord.model_validate_json(r["data"]) for r in rows]

    def get_open_picks(self) -> list[PickRecord]:
        """Return picks that do not yet have outcomes for ALL 3 horizons."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.data
                FROM   pick_records p
                WHERE  (
                    SELECT COUNT(DISTINCT o.horizon)
                    FROM   outcome_records o
                    WHERE  o.run_id = p.run_id
                ) < 3
                ORDER BY p.inserted_at
                """
            ).fetchall()
        return [PickRecord.model_validate_json(r["data"]) for r in rows]

    def get_outcomes(self, run_id: str) -> list[OutcomeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM outcome_records WHERE run_id = ? ORDER BY inserted_at",
                (run_id,),
            ).fetchall()
        return [OutcomeRecord.model_validate_json(r["data"]) for r in rows]

    def get_all_outcomes(self) -> list[OutcomeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM outcome_records ORDER BY inserted_at"
            ).fetchall()
        return [OutcomeRecord.model_validate_json(r["data"]) for r in rows]

    def get_baseline(self, run_id: str, horizon: str) -> RandomBaselineRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM baseline_records WHERE run_id = ? AND horizon = ?",
                (run_id, horizon),
            ).fetchone()
        if row is None:
            return None
        return RandomBaselineRecord.model_validate_json(row["data"])

    def get_all_baselines(self) -> list[RandomBaselineRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT data FROM baseline_records").fetchall()
        return [RandomBaselineRecord.model_validate_json(r["data"]) for r in rows]

    def get_universe(self, snapshot_id: str) -> UniverseSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM universe_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return UniverseSnapshot.model_validate_json(row["data"])

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_integrity(self) -> list[str]:
        """Re-hash every stored PickRecord; return run_ids where hash mismatches."""
        mismatches: list[str] = []
        for record in self.get_all_picks():
            stored_hash = record.record_hash
            recomputed = hash_record(record)
            if stored_hash != recomputed:
                mismatches.append(record.run_id)
        return mismatches
