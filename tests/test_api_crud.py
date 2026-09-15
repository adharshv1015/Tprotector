import pytest
from httpx import AsyncClient
from unittest.mock import patch
from app.services.encryption import decrypt_secret


@pytest.mark.asyncio
async def test_full_api_crud_lifecycle(client: AsyncClient):
    # 1. Create API with Bearer token (should be encrypted at rest)
    create_payload = {
        "name": "GitHub User API",
        "base_url": "https://api.github.com",
        "endpoint_path": "/user",
        "method": "GET",
        "auth_type": "bearer",
        "auth_config": {"token": "ghp_secret_token_12345"},
        "check_interval_minutes": 15,
        "rate_limit_header_limit": "X-RateLimit-Limit",
        "rate_limit_header_remaining": "X-RateLimit-Remaining"
    }

    create_res = await client.post("/apis", json=create_payload)
    assert create_res.status_code == 201
    created_data = create_res.json()
    api_id = created_data["id"]
    assert created_data["name"] == "GitHub User API"
    # Verify auth_config is not leaked in response
    assert "auth_config" not in created_data

    # 2. List APIs
    list_res = await client.get("/apis")
    assert list_res.status_code == 200
    apis = list_res.json()
    assert any(a["id"] == api_id for a in apis)

    # 3. Get API by ID
    get_res = await client.get(f"/apis/{api_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == api_id

    # 4. Patch API
    patch_payload = {
        "name": "GitHub User API (Updated)",
        "check_interval_minutes": 30
    }
    patch_res = await client.patch(f"/apis/{api_id}", json=patch_payload)
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "GitHub User API (Updated)"
    assert patch_res.json()["check_interval_minutes"] == 30

    # 5. Delete API
    del_res = await client.delete(f"/apis/{api_id}")
    assert del_res.status_code == 204

    # Confirm 404 after delete
    get_after_del = await client.get(f"/apis/{api_id}")
    assert get_after_del.status_code == 404
