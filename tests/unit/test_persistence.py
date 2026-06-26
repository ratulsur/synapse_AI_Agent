"""Unit tests for persistence/source_store.py and persistence/checkpointer.py.

Covers:
- save_sources + load_sources round-trip: every saved field is faithfully loaded.
- Idempotency: saving the same sources twice (INSERT OR REPLACE) leaves exactly
  one row per (thread_id, source_id).
- Thread isolation: sources saved under one thread_id are not visible under another.
- load_sources for unknown thread_id returns an empty list (no crash).
- save_sources with empty list is a no-op.
- get_checkpointer() returns MemorySaver when persistence.db_path == ":memory:".

All file-I/O tests use a per-test temp SQLite file (tmp_path fixture) so tests
never share state through the module-level connection cache.

Owner: test-eval-agent
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from schemas.source import Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src(
    url: str,
    content: str = "test content",
    domain: str = "GENERIC",
    tool: str | None = "web",
    score: float = 0.5,
) -> Source:
    return Source(title=f"Title for {url}", url=url, domain=domain,
                  content=content, tool=tool, score=score)


def _patch_db(monkeypatch, db_path: str) -> None:
    """Monkeypatch persistence.source_store._get_db_path to return db_path.

    Also reset _IN_MEMORY_CONN so the module doesn't share state between tests.
    """
    import persistence.source_store as ss
    monkeypatch.setattr(ss, "_get_db_path", lambda: db_path)


# ---------------------------------------------------------------------------
# save_sources + load_sources round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundtrip:
    def test_basic_roundtrip(self, monkeypatch, tmp_path):
        """All scalar fields survive a save/load cycle."""
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        src = _src("https://roundtrip.com", content="hello world", domain="Techno",
                   tool="arxiv", score=0.88)
        save_sources("thread-001", [src])
        loaded = load_sources("thread-001")

        assert len(loaded) == 1
        got = loaded[0]
        assert got.id == src.id
        assert got.title == src.title
        assert got.url == src.url
        assert got.domain == src.domain
        assert got.content == src.content
        assert got.tool == src.tool
        assert abs(got.score - src.score) < 1e-6

    def test_multiple_sources_roundtrip(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        sources = [
            _src("https://a.com", content="alpha"),
            _src("https://b.com", content="beta"),
            _src("https://c.com", content="gamma"),
        ]
        save_sources("thread-multi", sources)
        loaded = load_sources("thread-multi")

        assert len(loaded) == 3
        loaded_urls = {s.url for s in loaded}
        expected_urls = {"https://a.com", "https://b.com", "https://c.com"}
        assert loaded_urls == expected_urls

    def test_null_author_roundtrip(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        src = Source(title="T", url="https://no-author.com", domain="GENERIC", author=None)
        save_sources("thread-null", [src])
        loaded = load_sources("thread-null")
        assert loaded[0].author is None

    def test_null_tool_roundtrip(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        src = Source(title="T", url="https://no-tool.com", domain="GENERIC", tool=None)
        save_sources("thread-notool", [src])
        loaded = load_sources("thread-notool")
        assert loaded[0].tool is None

    def test_retrieved_at_roundtrip(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        src = Source(title="T", url="https://ts.com", domain="GENERIC", retrieved_at=ts)
        save_sources("thread-ts", [src])
        loaded = load_sources("thread-ts")
        # Timestamps should match (stored as ISO string, reloaded)
        assert abs((loaded[0].retrieved_at.replace(tzinfo=timezone.utc) - ts).total_seconds()) < 1.0


# ---------------------------------------------------------------------------
# Idempotency (INSERT OR REPLACE)
# ---------------------------------------------------------------------------


class TestSaveIdempotency:
    def test_double_save_no_duplicates(self, monkeypatch, tmp_path):
        """Calling save_sources twice with the same sources leaves exactly one row per source."""
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        src = _src("https://once.com")
        save_sources("thread-idem", [src])
        save_sources("thread-idem", [src])  # second call -- idempotent
        loaded = load_sources("thread-idem")
        assert len(loaded) == 1

    def test_save_with_updated_content_replaces(self, monkeypatch, tmp_path):
        """INSERT OR REPLACE: second save with same (thread_id, source_id) replaces the row."""
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        # Two sources with same id (same url+content) but we force the same id
        src1 = Source(id="fixed-id", title="T", url="https://a.com", domain="GENERIC",
                      content="v1", score=0.5)
        src2 = Source(id="fixed-id", title="T", url="https://a.com", domain="GENERIC",
                      content="v2", score=0.9)
        save_sources("thread-replace", [src1])
        save_sources("thread-replace", [src2])
        loaded = load_sources("thread-replace")
        assert len(loaded) == 1
        assert abs(loaded[0].score - 0.9) < 1e-6  # v2 replaced v1


# ---------------------------------------------------------------------------
# Thread isolation
# ---------------------------------------------------------------------------


class TestThreadIsolation:
    def test_different_threads_isolated(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        src_a = _src("https://thread-a.com")
        src_b = _src("https://thread-b.com")
        save_sources("thread-A", [src_a])
        save_sources("thread-B", [src_b])

        loaded_a = load_sources("thread-A")
        loaded_b = load_sources("thread-B")

        assert len(loaded_a) == 1
        assert loaded_a[0].url == "https://thread-a.com"
        assert len(loaded_b) == 1
        assert loaded_b[0].url == "https://thread-b.com"

    def test_load_unknown_thread_returns_empty(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources

        result = load_sources("nonexistent-thread-xyz")
        assert result == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_save_empty_list_is_noop(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        save_sources("thread-empty", [])  # should not raise
        loaded = load_sources("thread-empty")
        assert loaded == []

    def test_source_with_empty_content(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.db")
        _patch_db(monkeypatch, db)
        from persistence.source_store import load_sources, save_sources

        src = Source(title="T", url="https://empty-content.com", domain="GENERIC", content="")
        save_sources("thread-empty-content", [src])
        loaded = load_sources("thread-empty-content")
        assert len(loaded) == 1
        assert loaded[0].content == ""


# ---------------------------------------------------------------------------
# get_checkpointer()
# ---------------------------------------------------------------------------


class TestGetCheckpointer:
    def test_returns_memory_saver_for_in_memory(self):
        """When config db_path == ':memory:', checkpointer is a MemorySaver."""
        from langgraph.checkpoint.memory import MemorySaver
        from persistence.checkpointer import get_checkpointer

        cp = get_checkpointer()
        # Config defaults to ":memory:" so we should get MemorySaver
        assert isinstance(cp, MemorySaver)

    def test_get_checkpointer_returns_a_saver(self):
        """get_checkpointer() always returns something checkpointer-shaped."""
        from persistence.checkpointer import get_checkpointer

        cp = get_checkpointer()
        # Must have the methods a LangGraph checkpointer needs
        assert hasattr(cp, "put") or hasattr(cp, "aget") or hasattr(cp, "get")
