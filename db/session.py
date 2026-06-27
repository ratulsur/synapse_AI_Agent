"""Async SQLAlchemy engine, session factory, FastAPI dependency, and init helper.

URL resolution order
--------------------
1. ``DATABASE_URL`` environment variable (required in production).
2. Default: ``sqlite+aiosqlite:///./synapse.db`` (local dev / tests).

The resolver rewrites bare ``postgres://`` and ``postgresql://`` prefixes to
``postgresql+asyncpg://`` (asyncpg driver), and strips the ``sslmode=`` query
parameter that asyncpg rejects.

Owner: Ratul Sur
"""

from __future__ import annotations

import os
import urllib.parse
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from log import GLOBAL_LOGGER as log


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------


def _resolve_database_url() -> str:
    """Return the fully-qualified async database URL.

    Rewrites legacy ``postgres://`` / ``postgresql://`` prefixes and strips
    ``sslmode=`` query parameter (asyncpg rejects it).
    """
    url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./synapse.db")

    # Rewrite bare postgres:// → postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    # Strip sslmode= query parameter that asyncpg rejects
    if "?" in url:
        base, query_string = url.split("?", 1)
        params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
        params.pop("sslmode", None)
        if params:
            # Re-encode remaining params (take first value of each list)
            new_query = urllib.parse.urlencode(
                {k: v[0] for k, v in params.items()}
            )
            url = f"{base}?{new_query}"
        else:
            url = base

    return url


# ---------------------------------------------------------------------------
# Module-level engine and session factory (created once per process)
# ---------------------------------------------------------------------------

_DATABASE_URL: str = _resolve_database_url()
_IS_SQLITE: bool = "sqlite" in _DATABASE_URL

engine = create_async_engine(
    _DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    # pool_size / max_overflow are not supported by the aiosqlite dialect;
    # only set them for Postgres.
    **({} if _IS_SQLITE else {"pool_size": 5, "max_overflow": 10}),
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # mandatory — prevents lazy-load after commit
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` scoped to the current request."""
    async with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all tables on startup (SQLite and Postgres).

    Uses ``metadata.create_all`` with ``checkfirst=True`` so it is safe to call
    on every startup — existing tables are left untouched.  For production schema
    migrations (column changes, renames) use Alembic separately.
    """
    from db.models import Base  # noqa: PLC0415

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, checkfirst=True))
    log.info("db: tables ready")
