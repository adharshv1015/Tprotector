import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_without_sandbox_flag_fails(client: AsyncClient):
    """Mutating methods without is_sandbox=True must fail loudly with 422 Unprocessable Entity."""
    payload = {
        "name": "Stripe Charges Production (Accidental)",
        "base_url": "https://api.stripe.com",
        "endpoint_path": "/v1/charges",
        "method": "POST",
        "is_sandbox": False,
        "test_payload": {"amount": 1000, "currency": "usd"},
        "check_interval_minutes": 30
    }

    response = await client.post("/apis", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "require is_sandbox=True" in str(data)


@pytest.mark.asyncio
async def test_post_with_sandbox_flag_succeeds(client: AsyncClient):
    """Mutating methods with is_sandbox=True must succeed."""
    payload = {
        "name": "Stripe Charges Sandbox",
        "base_url": "https://api.stripe.com",
        "endpoint_path": "/v1/charges",
        "method": "POST",
        "is_sandbox": True,
        "test_payload": {"amount": 1000, "currency": "usd"},
        "check_interval_minutes": 30
    }

    response = await client.post("/apis", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["method"] == "POST"
    assert data["is_sandbox"] is True


@pytest.mark.asyncio
async def test_get_method_defaults_and_succeeds_without_sandbox(client: AsyncClient):
    """Safe GET requests do not require is_sandbox=True."""
    payload = {
        "name": "Public GitHub API",
        "base_url": "https://api.github.com",
        "endpoint_path": "/zen",
        "method": "GET",
        "is_sandbox": False,
        "check_interval_minutes": 60
    }

    response = await client.post("/apis", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["is_sandbox"] is False
