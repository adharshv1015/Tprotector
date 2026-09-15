import enum
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuthType(str, enum.Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"


class ApiStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"


class HttpMethod(str, enum.Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


# Cross-dialect JSON column type (JSONB on postgres, JSON on sqlite)
# none_as_null=True ensures python None is stored as SQL NULL rather than JSON 'null'
JSONType = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class TrackedAPI(Base):
    __tablename__ = "tracked_apis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    endpoint_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    method: Mapped[HttpMethod] = mapped_column(
        Enum(HttpMethod, native_enum=False), default=HttpMethod.GET, nullable=False
    )
    
    # Safety guardrail for mutating endpoints
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    test_payload: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    custom_headers: Mapped[Optional[Dict[str, str]]] = mapped_column(JSONType, nullable=True)

    # Auth configuration (stored encrypted at rest)
    auth_type: Mapped[AuthType] = mapped_column(
        Enum(AuthType, native_enum=False), default=AuthType.NONE, nullable=False
    )
    auth_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Scheduling
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    status: Mapped[ApiStatus] = mapped_column(
        Enum(ApiStatus, native_enum=False), default=ApiStatus.ACTIVE, nullable=False
    )

    # Rate limiting header keys (configurable per API)
    rate_limit_header_limit: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rate_limit_header_remaining: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rate_limit_header_reset: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Changelog / deprecation scraping
    changelog_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    last_changelog_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    snapshots: Mapped[List["ApiSnapshot"]] = relationship("ApiSnapshot", back_populates="tracked_api", cascade="all, delete-orphan")
    schema_diffs: Mapped[List["SchemaDiff"]] = relationship("SchemaDiff", back_populates="tracked_api", cascade="all, delete-orphan")
    rate_limits: Mapped[List["RateLimitTracking"]] = relationship("RateLimitTracking", back_populates="tracked_api", cascade="all, delete-orphan")
    deprecation_notices: Mapped[List["DeprecationNotice"]] = relationship("DeprecationNotice", back_populates="tracked_api", cascade="all, delete-orphan")
    latency_baselines: Mapped[List["LatencyBaseline"]] = relationship("LatencyBaseline", back_populates="tracked_api", cascade="all, delete-orphan")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="tracked_api", cascade="all, delete-orphan")
