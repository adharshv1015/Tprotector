from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event, EventSeverity
from app.schemas.event import EventResponse

router = APIRouter(prefix="/events", tags=["Event Timeline"])


@router.get("", response_model=List[EventResponse])
async def list_events(
    api_id: Optional[int] = Query(None, description="Filter by Tracked API ID"),
    severity: Optional[EventSeverity] = Query(None, description="Filter by event severity"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Retrieves the unified event timeline with optional filtering."""
    query = select(Event)

    if api_id is not None:
        query = query.where(Event.tracked_api_id == api_id)
    if severity is not None:
        query = query.where(Event.severity == severity)
    if event_type is not None:
        query = query.where(Event.event_type == event_type)

    query = query.order_by(Event.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())
