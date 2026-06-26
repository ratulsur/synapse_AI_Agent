"""SQLite checkpointer factory for the LangGraph StateGraph.

``get_checkpointer()`` returns a ``BaseCheckpointSaver`` so the graph can
persist state per ``thread_id``, survive process restarts, and resume from
human-in-the-loop interrupts.

Selection logic
---------------
* ``persistence.db_path == ":memory:"`` (the default)
  -> ``langgraph.checkpoint.memory.MemorySaver`` (in-process, no disk I/O).
* Any real file path
  -> ``langgraph.checkpoint.sqlite.SqliteSaver`` backed by a persistent
     SQLite file.  Falls back to ``MemorySaver`` if the
     ``langgraph-checkpoint-sqlite`` package is not installed.

DB path is read from ``config/configuration.yaml`` via
``utils.config_loader.load_config()``::

    persistence:
      db_path: "data/synapse_graph.db"   # set to a real path to enable SQLite

Owner: Ratul Sur
"""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.memory import MemorySaver

from exception.custom_exception import ResearchAnalystException
from log import GLOBAL_LOGGER as log
from utils.config_loader import load_config


def get_checkpointer():
    """Return a checkpointer instance appropriate for the configured db_path.

    Returns:
        ``MemorySaver`` when ``persistence.db_path`` is ``":memory:"``.
        ``SqliteSaver`` for a real file path.
        Falls back to ``MemorySaver`` if ``langgraph-checkpoint-sqlite`` is not
        installed.

    Raises:
        ResearchAnalystException: Only on unexpected configuration errors; the
        SQLite-unavailable case is handled gracefully.
    """
    try:
        cfg = load_config()
        db_path: str = cfg.get("persistence", {}).get("db_path", ":memory:")

        if db_path == ":memory:":
            log.debug("checkpointer: using in-memory MemorySaver (db_path=:memory:)")
            return MemorySaver()

        # Attempt to use the SQLite-backed saver for a real file path.
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import]

            conn = sqlite3.connect(db_path, check_same_thread=False)
            saver = SqliteSaver(conn)
            log.info("checkpointer: using SqliteSaver", db_path=db_path)
            return saver

        except ImportError:
            log.warning(
                "checkpointer: langgraph-checkpoint-sqlite not installed; "
                "falling back to MemorySaver",
                db_path=db_path,
            )
            return MemorySaver()

    except Exception as exc:
        msg = "get_checkpointer() failed"
        log.error(msg, error=str(exc))
        raise ResearchAnalystException(msg, exc) from exc
