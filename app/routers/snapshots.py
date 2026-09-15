from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schema_diff import SchemaDiff
from app.models.snapshot import ApiSnapshot
from app.models.tracked_api import TrackedAPI
from app.schemas.snapshot import ApiSnapshotResponse, SchemaDiffResponse
from app.services.latency import get_latest_baseline

router = APIRouter(prefix="/apis/{api_id}", tags=["Snapshots & Diffs"])


@router.get("/snapshots", response_model=List[ApiSnapshotResponse])
async def list_api_snapshots(
    api_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Lists historical snapshots for an API in descending order."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    query = (
        select(ApiSnapshot)
        .where(ApiSnapshot.tracked_api_id == api_id)
        .order_by(ApiSnapshot.checked_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/diffs", response_model=List[SchemaDiffResponse])
async def list_schema_diffs(
    api_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Lists schema diff history for an API in descending order."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    query = (
        select(SchemaDiff)
        .where(SchemaDiff.tracked_api_id == api_id)
        .order_by(SchemaDiff.detected_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/baseline")
async def get_api_baseline(
    api_id: int,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Retrieves current rolling latency baseline for an API."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    baseline = await get_latest_baseline(db, api_id)
    if not baseline:
        return {"tracked_api_id": api_id, "baseline": None, "message": "Baseline not calculated yet."}

    return {
        "tracked_api_id": api_id,
        "avg_response_time_ms": baseline.avg_response_time_ms,
        "std_dev_ms": baseline.std_dev_ms,
        "error_rate_percent": baseline.error_rate_percent,
        "window_start": baseline.window_start,
        "window_end": baseline.window_end,
    }
