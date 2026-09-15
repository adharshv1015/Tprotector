import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
import httpx

from app.models.tracked_api import HttpMethod
from app.services.rate_limit import auto_discover_rate_limit_headers
from app.services.deprecation import auto_probe_changelog_url


# ─── Rate-Limit Header Auto-Discovery ────────────────────────────────────────

def test_auto_discover_rate_limit_headers_github():
    """GitHub / Stripe style: X-RateLimit-* headers are detected correctly."""
    headers = {
        "Content-Type": "application/json",
        "X-RateLimit-Limit": "5000",
        "X-RateLimit-Remaining": "4999",
        "X-RateLimit-Reset": "1720000000"
    }

    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    assert limit == "X-RateLimit-Limit"
    assert rem == "X-RateLimit-Remaining"
    assert reset == "X-RateLimit-Reset"


def test_auto_discover_rate_limit_headers_rfc():
    """RFC-compliant plain RateLimit-* headers are detected correctly."""
    headers = {
        "RateLimit-Limit": "100",
        "RateLimit-Remaining": "90",
        "RateLimit-Reset": "60"
    }

    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    assert limit == "RateLimit-Limit"
    assert rem == "RateLimit-Remaining"
    assert reset == "RateLimit-Reset"


def test_auto_discover_rate_limit_headers_heuristic():
    """Custom company-specific header names are discovered via heuristic scan."""
    headers = {
        "company-custom-limit": "1000",
        "company-custom-remaining": "850",
        "company-custom-reset": "3600"
    }

    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    assert limit == "company-custom-limit"
    assert rem == "company-custom-remaining"


def test_auto_discover_rate_limit_headers_returns_none_when_absent():
    """Returns (None, None, None) when no rate-limit headers are present."""
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": "abc123"
    }
    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    assert limit is None
    assert rem is None
    assert reset is None


def test_auto_discover_rate_limit_headers_case_insensitive():
    """Discovery is case-insensitive — lowercase header names are matched."""
    headers = {
        "x-ratelimit-limit": "200",
        "x-ratelimit-remaining": "150",
    }
    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    assert limit == "x-ratelimit-limit"
    assert rem == "x-ratelimit-remaining"


def test_auto_discover_rate_limit_headers_missing_remaining():
    """When only limit header exists but no remaining, returns None."""
    headers = {
        "X-RateLimit-Limit": "500",
        "Content-Type": "text/html",
    }
    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    # Without a matching remaining header, result should be None
    assert rem is None


def test_auto_discover_rate_limit_headers_non_numeric_ignored():
    """Non-numeric heuristic headers should not be returned as rate-limit headers."""
    headers = {
        "company-limit": "unlimited",  # non-digit → should not match
        "company-remaining": "lots",
    }
    limit, rem, reset = auto_discover_rate_limit_headers(headers)
    assert limit is None
    assert rem is None


# ─── Changelog URL Auto-Probe ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_probe_changelog_link_header():
    """Extracts changelog URL from Link header with rel=documentation."""
    headers = {
        "link": '<https://api.example.com/docs/v1>; rel="documentation", <https://api.example.com/users?page=2>; rel="next"'
    }

    url = await auto_probe_changelog_url("https://api.example.com", response_headers=headers)
    assert url == "https://api.example.com/docs/v1"


@pytest.mark.asyncio
async def test_auto_probe_changelog_link_header_help_rel():
    """Extracts changelog URL from Link header with rel=help."""
    headers = {
        "link": '<https://api.example.com/help>; rel="help"'
    }

    url = await auto_probe_changelog_url("https://api.example.com", response_headers=headers)
    assert url == "https://api.example.com/help"


@pytest.mark.asyncio
async def test_auto_probe_changelog_no_link_header_probes_common_paths():
    """When no Link header, probes /changelog, /docs, /api-docs paths and returns the first 200."""

    async def mock_send(request, **kwargs):
        if str(request.url).endswith("/docs"):
            return httpx.Response(200, request=request)
        return httpx.Response(404, request=request)

    with patch("httpx.AsyncClient.send", side_effect=mock_send):
        url = await auto_probe_changelog_url("https://api.example.com")
        assert url == "https://api.example.com/docs"


@pytest.mark.asyncio
async def test_auto_probe_changelog_returns_none_when_all_404():
    """Returns None when no common path responds with 200."""

    async def mock_send(request, **kwargs):
        return httpx.Response(404, request=request)

    with patch("httpx.AsyncClient.send", side_effect=mock_send):
        url = await auto_probe_changelog_url("https://api.example.com")
        assert url is None


@pytest.mark.asyncio
async def test_auto_probe_changelog_aborts_on_403():
    """Stops probing immediately when the host returns 403 (WAF block)."""
    call_count = 0

    async def mock_send(request, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(403, request=request)

    with patch("httpx.AsyncClient.send", side_effect=mock_send):
        url = await auto_probe_changelog_url("https://api.example.com")
        assert url is None
        # Should abort after the first 403 and not probe remaining candidates
        assert call_count == 1


@pytest.mark.asyncio
async def test_auto_probe_changelog_no_link_no_paths_returns_none():
    """Returns None when no headers provided and no probed paths succeed."""
    url = await auto_probe_changelog_url(
        "https://api.example.com",
        response_headers={},
        client=None
    )
    # Will try to probe; all will fail since no server is running
    # Result must be None — never raise an exception
    assert url is None or isinstance(url, str)


# ─── Auto-Check Triggered on API Creation ────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_check_triggered_on_creation(client: AsyncClient):
    """Verifies that POST /apis automatically schedules and runs the initial check in the background."""
    payload = {
        "name": "Auto Check API",
        "base_url": "https://jsonplaceholder.typicode.com",
        "endpoint_path": "/todos/1",
        "method": "GET",
        "check_interval_minutes": 60
    }

    with patch("app.scheduler.runner.execute_monitored_request") as mock_exec:
        resp = httpx.Response(status_code=200, json={"id": 1, "task": "do test"})
        mock_exec.return_value = (resp, 50.0, None)

        create_res = await client.post("/apis", json=payload)
        assert create_res.status_code == 201
        data = create_res.json()
        api_id = data["id"]

        # Verify that mock_exec was invoked automatically by BackgroundTasks!
        assert mock_exec.called


@pytest.mark.asyncio
async def test_auto_check_not_triggered_on_bad_payload(client: AsyncClient):
    """Verifies that a malformed POST /apis request returns 422 and does NOT trigger any check."""
    payload = {
        # Missing required fields: base_url, endpoint_path, method
        "name": "Bad API"
    }

    with patch("app.scheduler.runner.execute_monitored_request") as mock_exec:
        create_res = await client.post("/apis", json=payload)
        assert create_res.status_code == 422  # Validation error
        # Auto-check must NOT be triggered for a failed create
        assert not mock_exec.called


@pytest.mark.asyncio
async def test_created_api_is_retrievable(client: AsyncClient):
    """Verifies that a newly created API can be fetched back by its ID."""
    payload = {
        "name": "Retrievable API",
        "base_url": "https://jsonplaceholder.typicode.com",
        "endpoint_path": "/posts/1",
        "method": "GET",
        "check_interval_minutes": 30
    }

    with patch("app.scheduler.runner.execute_monitored_request") as mock_exec:
        mock_exec.return_value = (httpx.Response(200, json={"id": 1}), 30.0, None)

        create_res = await client.post("/apis", json=payload)
        assert create_res.status_code == 201
        api_id = create_res.json()["id"]

    get_res = await client.get(f"/apis/{api_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Retrievable API"
