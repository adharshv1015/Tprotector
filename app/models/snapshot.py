from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.tracked_api import JSONType


class ApiSnapshot(Base):
    __tablename__ = "api_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_api_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracked_apis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Extracted structural schema, not full body (field names, types, nesting)
    response_schema: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    headers_snapshot: Mapped[Optional[Dict[str, str]]] = mapped_column(JSONType, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    tracked_api: Mapped["TrackedAPI"] = relationship("TrackedAPI", back_populates="snapshots")
