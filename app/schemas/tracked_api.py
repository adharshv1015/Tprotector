from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.tracked_api import ApiStatus, AuthType, HttpMethod


class TrackedAPIBase(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Client session identifier")
    name: str = Field(..., max_length=255, description="Descriptive name for the API")
    base_url: str = Field(..., max_length=1024, description="Base URL of the API e.g. https://api.stripe.com")
    endpoint_path: str = Field(..., max_length=1024, description="Path to monitor e.g. /v1/charges")
    method: HttpMethod = Field(default=HttpMethod.GET, description="HTTP Method")
    is_sandbox: bool = Field(
        default=False,
        description="Must be True for mutating methods (POST, PUT, PATCH, DELETE) to safeguard against production executions"
    )
    test_payload: Optional[Any] = Field(default=None, description="Request payload for POST/PUT/PATCH test calls")
    custom_headers: Optional[Dict[str, str]] = Field(default=None, description="Custom headers for test requests")
    auth_type: AuthType = Field(default=AuthType.NONE, description="Authentication scheme")
    auth_config: Optional[Dict[str, Any]] = Field(default=None, description="Plaintext auth config (encrypted before persistence)")
    check_interval_minutes: int = Field(default=60, ge=1, description="Interval in minutes between checks")
    status: ApiStatus = Field(default=ApiStatus.ACTIVE, description="Active or paused status")
    rate_limit_header_limit: Optional[str] = Field(default=None, description="Header name for limit")
    rate_limit_header_remaining: Optional[str] = Field(default=None, description="Header name for remaining quota")
    rate_limit_header_reset: Optional[str] = Field(default=None, description="Header name for reset epoch/seconds")
    changelog_url: Optional[str] = Field(default=None, description="URL of API changelog or documentation page")


class TrackedAPICreate(TrackedAPIBase):
    @model_validator(mode="after")
    def validate_sandbox_guardrail(self) -> "TrackedAPICreate":
        mutating_methods = {HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE}
        if self.method in mutating_methods and not self.is_sandbox:
            raise ValueError(
                "Mutating HTTP methods (POST, PUT, PATCH, DELETE) require is_sandbox=True "
                "to prevent accidental automated calls against production endpoints."
            )
        return self


class TrackedAPIUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    method: Optional[HttpMethod] = None
    is_sandbox: Optional[bool] = None
    test_payload: Optional[Any] = None
    custom_headers: Optional[Dict[str, str]] = None
    auth_type: Optional[AuthType] = None
    auth_config: Optional[Dict[str, Any]] = None
    check_interval_minutes: Optional[int] = Field(default=None, ge=1)
    status: Optional[ApiStatus] = None
    rate_limit_header_limit: Optional[str] = None
    rate_limit_header_remaining: Optional[str] = None
    rate_limit_header_reset: Optional[str] = None
    changelog_url: Optional[str] = None

    @model_validator(mode="after")
    def validate_update_sandbox_guardrail(self) -> "TrackedAPIUpdate":
        mutating_methods = {HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE}
        if self.method in mutating_methods and self.is_sandbox is False:
            raise ValueError(
                "Mutating HTTP methods (POST, PUT, PATCH, DELETE) require is_sandbox=True "
                "to prevent accidental automated calls against production endpoints."
            )
        return self


class TrackedAPIResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: Optional[str] = None
    name: str
    base_url: str
    endpoint_path: str
    method: HttpMethod
    is_sandbox: bool
    test_payload: Optional[Any] = None
    custom_headers: Optional[Dict[str, str]] = None
    auth_type: AuthType
    check_interval_minutes: int
    status: ApiStatus
    rate_limit_header_limit: Optional[str] = None
    rate_limit_header_remaining: Optional[str] = None
    rate_limit_header_reset: Optional[str] = None
    changelog_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Live health & operational status
    last_status_code: Optional[int] = None
    last_response_time_ms: Optional[float] = None
    last_checked_at: Optional[datetime] = None
    is_working: Optional[bool] = None
