import enum
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.tracked_api import JSONType


class DiffSeverity(str, enum.Enum):
    BREAKING = "breaking"
    NON_BREAKING = "non_breaking"
    INFORMATIONAL = "informational"


class SchemaDiff(Base):
    __tablename__ = "schema_diffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_api_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracked_apis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_schema: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    new_schema: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    diff_summary: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    severity: Mapped[DiffSeverity] = mapped_column(
        Enum(DiffSeverity, native_enum=False), default=DiffSeverity.INFORMATIONAL, nullable=False, index=True
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    tracked_api: Mapped["TrackedAPI"] = relationship("TrackedAPI", back_populates="schema_diffs")
