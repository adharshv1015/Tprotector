from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict

from app.models.event import EventSeverity


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracked_api_id: int
    event_type: str
    severity: EventSeverity
    message: str
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    created_at: datetime
