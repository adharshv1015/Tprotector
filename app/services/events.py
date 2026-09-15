import logging
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event, EventSeverity
from app.services.alerts import send_email_alert, send_slack_alert

logger = logging.getLogger(__name__)


async def record_event(
    db: AsyncSession,
    tracked_api_id: int,
    event_type: str,
    severity: EventSeverity,
    message: str,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None
) -> Event:
    """Persists a new event to the timeline and dispatches external alerts on high/breaking events."""
    event = Event(
        tracked_api_id=tracked_api_id,
        event_type=event_type,
        severity=severity,
        message=message,
        old_value=old_value,
        new_value=new_value
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # Trigger external notifications for high and breaking events
    if severity in (EventSeverity.HIGH, EventSeverity.BREAKING):
        alert_subject = f"[{severity.value.upper()}] API Monitor Alert: {event_type}"
        alert_body = f"{message}\n\nAPI ID: {tracked_api_id}\nSeverity: {severity.value}"
        
        try:
            await send_slack_alert(message=f"*{alert_subject}*\n{message}")
            await send_email_alert(subject=alert_subject, body=alert_body)
        except Exception as e:
            logger.error(f"Failed to dispatch notifications for event {event.id}: {e}")

    return event
