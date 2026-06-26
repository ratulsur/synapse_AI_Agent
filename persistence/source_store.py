"""Typed Source[] store backed by SQLite (the "Save + Checkpoint" node).

Persists deduped ``schemas.source.Source`` rows keyed by run ``thread_id`` +
``Source.id``, in a table separate from the LangGraph checkpoint blob so
sources are queryable and auditable independently.

DB path resolution
------------------
Uses ``persistence.source_db_path`` from ``config/configuration.yaml`` if
present; otherwise falls back to ``persistence.db_path``.  When the resolved
path is ``":memory:"`` a module-level singleton connection is used so all
callers within the same process share the same in-memory database.

Public API:
    save_sources(thread_id: str, sources: list[Source]) -> None
    load_sources(thread_id: str) -> list[Source]

Owner: backend-developer
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from schemas.source import Source
from utils.config_loader import load_config

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    thread_id    TEXT    NOT NULL,
    source_id    TEXT    NOT NULL,
    title        TEXT    NOT NULL DEFAULT '',
    author       TEXT,
    url          TEXT    NOT NULL DEFAULT '',
    domain       TEXT    NOT NULL DEFAULT 'GENERIC',
    content      TEXT    NOT NULL DEFAULT '',
    score        REAL    NOT NULL DEFAULT 0.0,
    tool         TEXT,
    retrieved_at TEXT    NOT NULL,
    PRIMARY KEY (thread_id, source_id)
)
"""

# ---------------------------------------------------------------------------
# Connection cache
# ---------------------------------------------------------------------------

# Module-level singleton for the ":memory:" case.
_IN_MEMORY_CONN: Optional[sqlite3.Connection] = None
# Cache of file-path -> Connection for persistent DBs.
_FILE_CONN_CACHE: dict[str, sqlite3.Connection] = {}


def _get_db_path() -> str:
    cfg = load_config().get("persistence", {})
    return str(cfg.get("source_db_path") or cfg.get("db_path") or ":memory:")


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Return (and lazily create) a connection for the given db_path."""
    global _IN_MEMORY_CONN

    if db_path == ":memory:":
        if _IN_MEMORY_CONN is None:
            _IN_MEMORY_CONN = sqlite3.connect(":memory:", check_same_thread=False)
            _IN_MEMORY_CONN.execute(_CREATE_TABLE_SQL)
            _IN_MEMORY_CONN.commit()
            log.debug("source_store: created in-memory SQLite connection")
        return _IN_MEMORY_CONN

    if db_path not in _FILE_CONN_CACHE:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
        _FILE_CONN_CACHE[db_path] = conn
        log.debug("source_store: opened SQLite connection", db_path=db_path)

    return _FILE_CONN_CACHE[db_path]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_sources(thread_id: str, sources: list[Source]) -> None:
    """Persist a list of Sources to SQLite keyed by thread_id.

    Uses ``INSERT OR REPLACE`` so re-running a thread_id is idempotent.

    Args:
        thread_id: The LangGraph run / thread identifier.
        sources:   The deduped list of Source objects to persist.
    """
    if not sources:
        return

    try:
        db_path = _get_db_path()
        conn = _get_conn(db_path)

        rows = [
            (
                thread_id,
                s.id,
                s.title,
                s.author,
                s.url,
                s.domain,
                s.content,
                float(s.score),
                s.tool,
                s.retrieved_at.isoformat(),
            )
            for s in sources
        ]

        conn.executemany(
            "INSERT OR REPLACE INTO sources "
            "(thread_id, source_id, title, author, url, domain, content, score, tool, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

        log.info(
            "source_store.save_sources: persisted",
            thread_id=thread_id,
            count=len(sources),
            db_path=db_path,
        )

    except Exception as exc:
        msg = "save_sources() failed"
        log.error(msg, thread_id=thread_id, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc


def load_sources(thread_id: str) -> list[Source]:
    """Load all Sources previously saved for a thread_id.

    Args:
        thread_id: The LangGraph run / thread identifier.

    Returns:
        List of Source objects in insertion order, or [] if none found.
    """
    try:
        db_path = _get_db_path()
        conn = _get_conn(db_path)

        cursor = conn.execute(
            "SELECT source_id, title, author, url, domain, content, score, tool, retrieved_at "
            "FROM sources WHERE thread_id = ? ORDER BY rowid",
            (thread_id,),
        )

        sources: list[Source] = []
        for row in cursor:
            (
                source_id,
                title,
                author,
                url,
                domain,
                content,
                score,
                tool,
                retrieved_at_str,
            ) = row

            try:
                retrieved_at = datetime.fromisoformat(retrieved_at_str)
            except Exception:  # noqa: BLE001
                retrieved_at = datetime.now(tz=timezone.utc)

            sources.append(
                Source(
                    id=source_id,
                    title=title or "",
                    author=author,
                    url=url or "",
                    domain=domain or "GENERIC",
                    content=content or "",
                    score=float(score or 0.0),
                    tool=tool,
                    retrieved_at=retrieved_at,
                )
            )

        log.debug(
            "source_store.load_sources: loaded",
            thread_id=thread_id,
            count=len(sources),
        )
        return sources

    except Exception as exc:
        msg = "load_sources() failed"
        log.error(msg, thread_id=thread_id, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
