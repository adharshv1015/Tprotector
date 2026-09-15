from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DeprecationNotice(Base):
    __tablename__ = "deprecation_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_api_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracked_apis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    notice_text: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    tracked_api: Mapped["TrackedAPI"] = relationship("TrackedAPI", back_populates="deprecation_notices")
