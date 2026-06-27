"""Dashboard routes: run list, report retrieval, and analytics.

DTOs
----
RunListItem       -- id, query, status, created_at, duration_ms, has_report
RunListResponse   -- items, page, limit, total
ReportResponse    -- run_id, title, content, section_count, source_count, grounded, created_at
AnalyticsResponse -- total_runs, completed_runs, avg_duration_ms, runs_by_day,
                     top_domains, avg_sources_per_run

Routes
------
GET /dashboard/runs                   → RunListResponse  (paginated, filterable by status)
GET /dashboard/runs/{run_id}/report   → ReportResponse   (404 if no report or wrong owner)
GET /dashboard/analytics              → AnalyticsResponse

All routes require a valid Bearer JWT (via ``get_current_user``).

Owner: Ratul Sur
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.security import get_current_user
from db import crud
from db.models import User
from db.session import get_session
from log import GLOBAL_LOGGER as log

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class RunListItem(BaseModel):
    id: str
    query: str
    status: str
    created_at: datetime
    duration_ms: int | None
    has_report: bool


class RunListResponse(BaseModel):
    items: list[RunListItem]
    page: int
    limit: int
    total: int


class ReportResponse(BaseModel):
    run_id: str
    title: str
    content: str
    section_count: int
    source_count: int
    grounded: bool
    created_at: datetime


class AnalyticsResponse(BaseModel):
    total_runs: int
    completed_runs: int
    avg_duration_ms: float | None
    runs_by_day: list[dict]
    top_domains: list[dict]
    avg_sources_per_run: float | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    page: int = 1,
    limit: int = Query(20, le=100),
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> RunListResponse:
    """Return a paginated list of the current user's runs.

    Optional ``status`` filter narrows results to a specific lifecycle state
    (e.g. ``"completed"``, ``"awaiting_plan_approval"``).
    """
    runs, total = await crud.list_runs(
        db,
        user_id=user.id,
        page=page,
        limit=limit,
        status=status,
    )

    items: list[RunListItem] = [
        RunListItem(
            id=str(run.id),
            query=run.query,
            status=run.status,
            created_at=run.created_at,
            duration_ms=run.duration_ms,
            has_report=run.report is not None,
        )
        for run in runs
    ]

    log.info(
        "dashboard: list_runs",
        user_id=str(user.id),
        page=page,
        total=total,
    )
    return RunListResponse(items=items, page=page, limit=limit, total=total)


@router.get("/runs/{run_id}/report", response_model=ReportResponse)
async def get_report(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ReportResponse:
    """Return the report for a completed run.

    Verifies that the run belongs to the authenticated user via a JOIN.
    Returns HTTP 404 if the report does not exist or is owned by another user.
    """
    report = await crud.get_report_for_user(
        db,
        run_id=run_id,
        user_id=user.id,
    )
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found or access denied.",
        )

    return ReportResponse(
        run_id=str(report.run_id),
        title=report.title,
        content=report.content,
        section_count=report.section_count,
        source_count=report.source_count,
        grounded=report.grounded,
        created_at=report.created_at,
    )


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> AnalyticsResponse:
    """Return aggregate analytics for the current user's dashboard."""
    data = await crud.analytics(db, user_id=user.id)
    log.info("dashboard: analytics", user_id=str(user.id))
    return AnalyticsResponse(**data)
