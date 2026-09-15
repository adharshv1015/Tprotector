from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LatencyBaseline(Base):
    __tablename__ = "latency_baseline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_api_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracked_apis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    avg_response_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    std_dev_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error_rate_percent: Mapped[float] = mapped_column(Float, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tracked_api: Mapped["TrackedAPI"] = relationship("TrackedAPI", back_populates="latency_baselines")
