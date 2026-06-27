"""Alembic async migration environment.

Supports both offline mode (generates SQL script) and online mode (applies
migrations directly against the database).  The database URL is resolved at
runtime via ``db.session._resolve_database_url()`` so no URL is baked into
``alembic.ini``.

Async online migrations use ``create_async_engine`` with ``NullPool`` (so the
engine is not reused across migration runs) and ``conn.run_sync`` to hand off
to the sync Alembic context.

Owner: Ratul Sur
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Import Base from our models so Alembic can compare the schema.
from db.models import Base
from db.session import _resolve_database_url

# ---------------------------------------------------------------------------
# Alembic configuration
# ---------------------------------------------------------------------------

config = context.config
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------


def do_run_migrations(connection) -> None:
    """Configure the Alembic context against a sync connection and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without a live DB connection.

    Useful for generating SQL scripts to review before applying.
    """
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations against the live database using an async engine."""
    connectable = create_async_engine(
        _resolve_database_url(),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
