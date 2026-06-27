"""Initial schema: users, runs, reports, events.

Revision ID: 0001
Revises:
Create Date: 2026-06-27

Dialect notes
-------------
- PostgreSQL: creates the ``pgcrypto`` extension for UUID generation and a
  functional unique index on ``lower(email)`` for case-insensitive uniqueness.
- SQLite: creates a plain unique index on ``email`` (SQLite does not support
  functional indexes without custom collation; application code lower-cases
  before storage so this is equivalent).
- The ``active_domains`` and ``payload`` columns use plain JSON, which Alembic
  renders identically on both dialects; the ``with_variant(JSONB, ...)`` hint
  in the model is applied at query time by the ORM, not at schema creation time.

Owner: Ratul Sur
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple | None = None
depends_on: str | tuple | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    is_pg: bool = bind.dialect.name == "postgresql"

    # PostgreSQL: pgcrypto provides gen_random_uuid() used by older PG setups.
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "display_name",
            sa.String(120),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
    )

    # Email uniqueness index (case-insensitive on Postgres, plain on SQLite).
    if is_pg:
        op.create_index(
            "ux_users_email_lower",
            "users",
            [sa.text("lower(email)")],
            unique=True,
        )
    else:
        op.create_index(
            "ux_users_email",
            "users",
            ["email"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="awaiting_plan_approval",
        ),
        sa.Column("active_domains", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_runs_user_created", "runs", ["user_id", "created_at"])
    op.create_index("ix_runs_status", "runs", ["status"])

    # ------------------------------------------------------------------
    # reports
    # ------------------------------------------------------------------
    op.create_table(
        "reports",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "section_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "source_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "grounded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_events_run_created", "events", ["run_id", "created_at"])
    op.create_index("ix_events_run_type", "events", ["run_id", "event_type"])


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("reports")
    op.drop_table("runs")
    op.drop_table("users")
