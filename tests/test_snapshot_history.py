from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema_diff import DiffSeverity, SchemaDiff
from app.models.snapshot import ApiSnapshot
from app.models.tracked_api import ApiStatus, HttpMethod, TrackedAPI
from app.services.schema_diff import diff_schemas, extract_schema


@pytest.mark.asyncio
async def test_snapshot_precedence_skips_error_states(db_session: AsyncSession):
    """Verifies that schema diffing retrieves the most recent successful snapshot with a valid schema,
    cleanly skipping intermediate network errors or 5xx outages without corrupting diff calculations.
    """
    # Create Tracked API
    api = TrackedAPI(
        name="Test Gateway",
        base_url="https://api.example.com",
        endpoint_path="/v1/status",
        method=HttpMethod.GET,
        status=ApiStatus.ACTIVE
    )
    db_session.add(api)
    await db_session.commit()
    await db_session.refresh(api)

    t0 = datetime.now(timezone.utc)

    # 1. First Check: returns null field
    snap1_schema = extract_schema({"result": None})
    snap1 = ApiSnapshot(
        tracked_api_id=api.id,
        response_schema=snap1_schema,
        status_code=200,
        response_time_ms=55.0,
        headers_snapshot={},
        checked_at=t0
    )
    db_session.add(snap1)
    await db_session.commit()

    # 2. Second Check: Network Failure / 500 Outage (response_schema is None)
    snap2 = ApiSnapshot(
        tracked_api_id=api.id,
        response_schema=None,
        status_code=500,
        response_time_ms=1200.0,
        headers_snapshot={},
        checked_at=t0 + timedelta(minutes=5)
    )
    db_session.add(snap2)
    await db_session.commit()

    # 3. Third Check: Success with populated string (diff must compare against snap1, skipping snap2)
    snap3_schema = extract_schema({"result": "success"})
    
    # Query last successful snapshot with valid schema prior to snap3
    query = (
        select(ApiSnapshot)
        .where(
            ApiSnapshot.tracked_api_id == api.id,
            ApiSnapshot.response_schema.is_not(None),
            ApiSnapshot.status_code >= 200,
            ApiSnapshot.status_code < 300
        )
        .order_by(ApiSnapshot.checked_at.desc())
        .limit(1)
    )
    res = await db_session.execute(query)
    last_valid_snapshot = res.scalars().first()

    assert last_valid_snapshot.id == snap1.id

    severity, diff = diff_schemas(last_valid_snapshot.response_schema, snap3_schema)
    assert severity == DiffSeverity.INFORMATIONAL

    snap3 = ApiSnapshot(
        tracked_api_id=api.id,
        response_schema=snap3_schema,
        status_code=200,
        response_time_ms=60.0,
        headers_snapshot={},
        checked_at=t0 + timedelta(minutes=10)
    )
    db_session.add(snap3)
    await db_session.commit()

    # 4. Fourth Check: Breaking change (string to int)
    snap4_schema = extract_schema({"result": 200})
    
    query4 = (
        select(ApiSnapshot)
        .where(
            ApiSnapshot.tracked_api_id == api.id,
            ApiSnapshot.response_schema.is_not(None)
        )
        .order_by(ApiSnapshot.checked_at.desc())
        .limit(1)
    )
    res4 = await db_session.execute(query4)
    last_valid_4 = res4.scalars().first()

    assert last_valid_4.id == snap3.id

    severity4, diff4 = diff_schemas(last_valid_4.response_schema, snap4_schema)
    assert severity4 == DiffSeverity.BREAKING
