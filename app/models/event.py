import enum
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.tracked_api import JSONType


class EventSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BREAKING = "breaking"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_api_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracked_apis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, native_enum=False), default=EventSeverity.INFO, nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    new_value: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    tracked_api: Mapped["TrackedAPI"] = relationship("TrackedAPI", back_populates="events")
