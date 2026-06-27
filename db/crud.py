"""Async CRUD helpers for the synapse-ai-agent persistence layer.

All public functions accept ``run_id`` / ``user_id`` as ``str | uuid.UUID``
and coerce to ``UUID`` at the boundary so callers can pass either form.

Transaction discipline
----------------------
Each function commits its own transaction so callers do not need to call
``await db.commit()`` separately.  The exception is batch-write callers (e.g.
the SSE stream generator) that open their own session and commit once after
writing all events — they pass ``commit=False`` to ``write_event``.

Owner: Ratul Sur
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Event, Report, Run, User
from db.session import _IS_SQLITE
from log import GLOBAL_LOGGER as log


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Coerce a string or UUID to ``uuid.UUID``."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------


async def create_run(
    db: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
    query: str,
    status: str = "awaiting_plan_approval",
    active_domains: list[str] | None = None,
) -> Run:
    """Insert a new run row.  ``run_id`` must equal the LangGraph thread_id."""
    run = Run(
        id=_to_uuid(run_id),
        user_id=_to_uuid(user_id),
        query=query,
        status=status,
        active_domains=active_domains,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    log.info("db: run created", run_id=str(run_id), status=status)
    return run


async def get_run_for_user(
    db: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
) -> Run | None:
    """Return the run iff it belongs to ``user_id``; else ``None``."""
    result = await db.execute(
        select(Run).where(
            Run.id == _to_uuid(run_id),
            Run.user_id == _to_uuid(user_id),
        )
    )
    return result.scalar_one_or_none()


async def complete_run(
    db: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    active_domains: list[str] | None,
    low_confidence: bool,
) -> None:
    """Mark a run as completed, recording duration and active domains.

    ``duration_ms`` is computed from ``run.created_at`` to now (UTC).
    ``low_confidence`` is logged but not persisted as a separate column;
    the status is always set to ``"completed"``.
    """
    run_uuid = _to_uuid(run_id)
    result = await db.execute(select(Run).where(Run.id == run_uuid))
    run = result.scalar_one_or_none()
    if run is None:
        log.warning("db: complete_run called for unknown run_id", run_id=str(run_id))
        return

    now = datetime.now(timezone.utc)
    duration_ms: int | None = None
    if run.created_at is not None:
        created_at = run.created_at
        # SQLite returns naive datetimes; treat them as UTC.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        diff = now - created_at
        duration_ms = max(0, int(diff.total_seconds() * 1000))

    run.status = "completed"
    run.completed_at = now
    run.duration_ms = duration_ms
    if active_domains is not None:
        run.active_domains = active_domains

    await db.commit()
    log.info(
        "db: run completed",
        run_id=str(run_id),
        duration_ms=duration_ms,
        low_confidence=low_confidence,
    )


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


async def upsert_report(
    db: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    title: str,
    content: str,
    section_count: int,
    source_count: int,
    grounded: bool,
) -> Report:
    """Insert or update the report for a run (idempotent).

    Uses ``INSERT ON CONFLICT DO UPDATE`` on Postgres and a
    SELECT-then-INSERT/UPDATE on SQLite.
    """
    run_uuid = _to_uuid(run_id)

    if not _IS_SQLITE:
        # Postgres path: dialect-native upsert.
        from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

        stmt = (
            pg_insert(Report)
            .values(
                id=uuid.uuid4(),
                run_id=run_uuid,
                title=title,
                content=content,
                section_count=section_count,
                source_count=source_count,
                grounded=grounded,
            )
            .on_conflict_do_update(
                index_elements=["run_id"],
                set_={
                    "title": title,
                    "content": content,
                    "section_count": section_count,
                    "source_count": source_count,
                    "grounded": grounded,
                },
            )
        )
        await db.execute(stmt)
        await db.commit()
        # Re-query to return the ORM object.
        result = await db.execute(select(Report).where(Report.run_id == run_uuid))
        report = result.scalar_one()
    else:
        # SQLite path: SELECT then INSERT or UPDATE.
        result = await db.execute(select(Report).where(Report.run_id == run_uuid))
        report = result.scalar_one_or_none()
        if report is None:
            report = Report(
                run_id=run_uuid,
                title=title,
                content=content,
                section_count=section_count,
                source_count=source_count,
                grounded=grounded,
            )
            db.add(report)
        else:
            report.title = title
            report.content = content
            report.section_count = section_count
            report.source_count = source_count
            report.grounded = grounded
        await db.commit()
        await db.refresh(report)

    log.info(
        "db: report upserted",
        run_id=str(run_id),
        section_count=section_count,
        source_count=source_count,
        grounded=grounded,
    )
    return report


async def get_report_for_user(
    db: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
) -> Report | None:
    """Return the report for a run, verifying that the run belongs to ``user_id``."""
    result = await db.execute(
        select(Report)
        .join(Run, Report.run_id == Run.id)
        .where(
            Report.run_id == _to_uuid(run_id),
            Run.user_id == _to_uuid(user_id),
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------


async def write_event(
    db: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """Append an event row for a run.

    Pass ``commit=False`` when batching multiple events in one transaction
    (the caller must commit the session afterwards).
    """
    event = Event(
        run_id=_to_uuid(run_id),
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    if commit:
        await db.commit()


async def events_exist(db: AsyncSession, run_id: str | uuid.UUID) -> bool:
    """Return ``True`` if at least one event row exists for this run."""
    result = await db.execute(
        select(Event.id).where(Event.run_id == _to_uuid(run_id)).limit(1)
    )
    return result.first() is not None


# ---------------------------------------------------------------------------
# Run list + pagination
# ---------------------------------------------------------------------------


async def list_runs(
    db: AsyncSession,
    *,
    user_id: str | uuid.UUID,
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> tuple[list[Run], int]:
    """Return a page of runs for ``user_id`` plus the total count.

    The ``report`` relationship is eagerly loaded so callers can check
    ``run.report is not None`` without an extra query.
    """
    user_uuid = _to_uuid(user_id)
    filters: list = [Run.user_id == user_uuid]
    if status is not None:
        filters.append(Run.status == status)

    # Total count
    count_stmt = select(func.count(Run.id)).where(*filters)
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Paginated runs with report relationship loaded
    offset = (page - 1) * limit
    runs_stmt = (
        select(Run)
        .options(selectinload(Run.report))
        .where(*filters)
        .order_by(Run.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(runs_stmt)
    runs = list(result.scalars().all())

    return runs, total


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


async def analytics(
    db: AsyncSession,
    *,
    user_id: str | uuid.UUID,
) -> dict[str, Any]:
    """Return dashboard analytics for a user.

    Queries
    -------
    - ``total_runs``: all runs scoped to user.
    - ``completed_runs``: runs with status="completed".
    - ``avg_duration_ms``: average duration of completed runs (ms).
    - ``runs_by_day``: run counts per day for the last 30 days.
    - ``top_domains``: top 6 active_domains across all runs (Python-side tally).
    - ``avg_sources_per_run``: average report.source_count over user's reports.
    """
    user_uuid = _to_uuid(user_id)

    # Total runs
    total_runs: int = (
        await db.execute(select(func.count(Run.id)).where(Run.user_id == user_uuid))
    ).scalar_one()

    # Completed runs
    completed_runs: int = (
        await db.execute(
            select(func.count(Run.id)).where(
                Run.user_id == user_uuid,
                Run.status == "completed",
            )
        )
    ).scalar_one()

    # Average duration_ms (completed runs only)
    avg_duration_ms_raw = (
        await db.execute(
            select(func.avg(Run.duration_ms)).where(
                Run.user_id == user_uuid,
                Run.status == "completed",
                Run.duration_ms.is_not(None),
            )
        )
    ).scalar_one()
    avg_duration_ms: float | None = (
        float(avg_duration_ms_raw) if avg_duration_ms_raw is not None else None
    )

    # Runs by day (last 30 days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    runs_by_day_result = await db.execute(
        select(
            func.date(Run.created_at).label("day"),
            func.count(Run.id).label("count"),
        )
        .where(
            Run.user_id == user_uuid,
            Run.created_at >= thirty_days_ago,
        )
        .group_by(func.date(Run.created_at))
        .order_by(func.date(Run.created_at))
    )
    runs_by_day: list[dict] = [
        {"day": str(row.day), "count": row.count}
        for row in runs_by_day_result.fetchall()
    ]

    # Top domains — load active_domains arrays and tally in Python
    domains_result = await db.execute(
        select(Run.active_domains).where(
            Run.user_id == user_uuid,
            Run.active_domains.is_not(None),
        )
    )
    counter: Counter[str] = Counter()
    for (domains,) in domains_result.fetchall():
        if isinstance(domains, list):
            counter.update(str(d) for d in domains if d)
    top_domains: list[dict] = [
        {"domain": d, "count": c} for d, c in counter.most_common(6)
    ]

    # Average sources per run (over user's reports)
    avg_sources_raw = (
        await db.execute(
            select(func.avg(Report.source_count))
            .join(Run, Report.run_id == Run.id)
            .where(Run.user_id == user_uuid)
        )
    ).scalar_one()
    avg_sources_per_run: float | None = (
        float(avg_sources_raw) if avg_sources_raw is not None else None
    )

    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "avg_duration_ms": avg_duration_ms,
        "runs_by_day": runs_by_day,
        "top_domains": top_domains,
        "avg_sources_per_run": avg_sources_per_run,
    }
