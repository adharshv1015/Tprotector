from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict

from app.models.schema_diff import DiffSeverity


class ApiSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracked_api_id: int
    response_schema: Optional[Any] = None
    status_code: int
    response_time_ms: float
    headers_snapshot: Optional[Dict[str, str]] = None
    checked_at: datetime


class SchemaDiffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracked_api_id: int
    old_schema: Optional[Any] = None
    new_schema: Optional[Any] = None
    diff_summary: Optional[Any] = None
    header_changes: Optional[Dict[str, Any]] = None
    historical_leaks: Optional[list[str]] = None
    payload_bytes: Optional[int] = None
    format_evolution: Optional[Dict[str, str]] = None
    rate_limit_erosion: Optional[Dict[str, int]] = None
    severity: DiffSeverity
    detected_at: datetime


class DeepHistoryResponse(BaseModel):
    first_seen_at: datetime
    diffs: list[SchemaDiffResponse]


class HistoricalEndpoint(BaseModel):
    path: str
    last_seen_in_archive: datetime
    current_status: int


class TopologyArcheologyResponse(BaseModel):
    ghost_endpoints: list[HistoricalEndpoint]
    active_historical_endpoints: list[HistoricalEndpoint]
