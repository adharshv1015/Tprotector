from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RateLimitTracking(Base):
    __tablename__ = "rate_limit_tracking"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_api_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracked_apis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    limit_header_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remaining_header_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reset_header_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    usage_percent: Mapped[float] = mapped_column(Float, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    tracked_api: Mapped["TrackedAPI"] = relationship("TrackedAPI", back_populates="rate_limits")
