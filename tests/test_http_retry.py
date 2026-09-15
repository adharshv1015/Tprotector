import pytest
from unittest.mock import AsyncMock, patch
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.snapshot import ApiSnapshot
from app.models.tracked_api import ApiStatus, HttpMethod, TrackedAPI
from app.scheduler.runner import run_full_check
from app.services.http_client import execute_monitored_request


@pytest.mark.asyncio
async def test_http_retry_absorbs_transient_failure():
    """Verifies that execute_monitored_request retries on transient 5xx and recovers."""
    tracked_api = TrackedAPI(
        id=1,
        name="Mock API",
        base_url="https://mock.example.com",
        endpoint_path="/data",
        method=HttpMethod.GET,
        status=ApiStatus.ACTIVE
    )

    attempt_count = 0

    async def mock_request(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return httpx.Response(status_code=503, content=b'{"error": "temporarily unavailable"}')
        return httpx.Response(status_code=200, content=b'{"status": "ok"}')

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=mock_request)

    response, elapsed, error = await execute_monitored_request(
        tracked_api=tracked_api,
        max_retries=2,
        client=mock_client
    )

    assert attempt_count == 2
    assert response is not None
    assert response.status_code == 200
    assert error is None


@pytest.mark.asyncio
async def test_snapshot_deduplication_invariant(db_session: AsyncSession):
    """Guarantees that a check with transient retry creates exactly ONE snapshot row."""
    # Insert an active tracked API into the DB
    tracked_api = TrackedAPI(
        name="Resilience Test API",
        base_url="https://api.test.com",
        endpoint_path="/resource",
        method=HttpMethod.GET,
        status=ApiStatus.ACTIVE,
        check_interval_minutes=60
    )
    db_session.add(tracked_api)
    await db_session.commit()
    await db_session.refresh(tracked_api)

    attempt = 0

    async def transient_mock_request(api, max_retries=None, client=None):
        nonlocal attempt
        attempt += 2  # Simulates 2 attempts occurred internally in http_client
        resp = httpx.Response(status_code=200, json={"message": "recovered after retry"})
        return resp, 85.0, None

    with patch("app.scheduler.runner.execute_monitored_request", side_effect=transient_mock_request):
        with patch("app.scheduler.runner.AsyncSessionLocal", return_value=db_session):
            snapshot = await run_full_check(tracked_api.id)

    assert snapshot is not None

    # Invariant assertion: Exactly one snapshot row in api_snapshots
    query = select(ApiSnapshot).where(ApiSnapshot.tracked_api_id == tracked_api.id)
    result = await db_session.execute(query)
    snapshots = list(result.scalars().all())

    assert len(snapshots) == 1
    assert snapshots[0].status_code == 200
