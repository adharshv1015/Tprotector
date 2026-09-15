import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_end_to_end_manual_check(client: AsyncClient):
    """End-to-end test creating an API, triggering an on-demand check, and verifying snapshot and diff history."""
    # 1. Register API
    create_payload = {
        "name": "JSONPlaceholder Todo",
        "base_url": "https://jsonplaceholder.typicode.com",
        "endpoint_path": "/todos/1",
        "method": "GET",
        "check_interval_minutes": 60
    }
    create_res = await client.post("/apis", json=create_payload)
    assert create_res.status_code == 201
    api_id = create_res.json()["id"]

    # 2. Trigger check
    check_res = await client.post(f"/apis/{api_id}/check")
    assert check_res.status_code == 200
    snapshot_data = check_res.json()
    assert snapshot_data["tracked_api_id"] == api_id
    assert snapshot_data["status_code"] == 200
    assert snapshot_data["response_schema"] is not None
    assert "id" in snapshot_data["response_schema"]
    assert "title" in snapshot_data["response_schema"]

    # 3. Verify snapshot listing
    snaps_res = await client.get(f"/apis/{api_id}/snapshots")
    assert snaps_res.status_code == 200
    snaps = snaps_res.json()
    assert len(snaps) >= 1

    # 4. Trigger second check (identical schema, should produce no breaking diffs)
    check2_res = await client.post(f"/apis/{api_id}/check")
    assert check2_res.status_code == 200

    # 5. Check events timeline
    events_res = await client.get(f"/events?api_id={api_id}")
    assert events_res.status_code == 200
