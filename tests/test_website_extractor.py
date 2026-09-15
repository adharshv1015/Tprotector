import pytest
from httpx import AsyncClient

from app.services.service_classifier import (
    DiscoverySource,
    EndpointAccessibility,
    EndpointAvailability,
    calculate_confidence_score,
    classify_service,
    evaluate_endpoint_status,
)
from app.services.ssrf_protection import SSRFValidationError, validate_target_url
from app.services.website_api_extractor import EndpointIntelligence, WebsiteApiReport


def test_ssrf_validator_blocks_internal_hosts():
    with pytest.raises(SSRFValidationError):
        validate_target_url("http://localhost:8000/api")

    with pytest.raises(SSRFValidationError):
        validate_target_url("http://127.0.0.1:8080")

    with pytest.raises(SSRFValidationError):
        validate_target_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(SSRFValidationError):
        validate_target_url("http://192.168.1.1/admin")


def test_ssrf_validator_permits_public_urls():
    valid = validate_target_url("https://maktalseo.com")
    assert valid.startswith("https://maktalseo.com")


def test_evaluate_endpoint_status_availability_vs_accessibility():
    # 200 is ONLINE & OPEN
    avail, access = evaluate_endpoint_status(200)
    assert avail == EndpointAvailability.ONLINE
    assert access == EndpointAccessibility.OPEN

    # 401 is ONLINE & PROTECTED (endpoint exists!)
    avail401, access401 = evaluate_endpoint_status(401)
    assert avail401 == EndpointAvailability.ONLINE
    assert access401 == EndpointAccessibility.PROTECTED

    # 403 is ONLINE & SHIELDED (firewall/CDN)
    avail403, access403 = evaluate_endpoint_status(403)
    assert avail403 == EndpointAvailability.ONLINE
    assert access403 == EndpointAccessibility.SHIELDED

    # 405 is ONLINE & METHOD_RESTRICTED (needs POST/PUT)
    avail405, access405 = evaluate_endpoint_status(405)
    assert avail405 == EndpointAvailability.ONLINE
    assert access405 == EndpointAccessibility.METHOD_RESTRICTED

    # 404 is NOT_FOUND
    avail404, access404 = evaluate_endpoint_status(404)
    assert avail404 == EndpointAvailability.NOT_FOUND


def test_confidence_scoring():
    # WordPress Index + 200 OK -> 98% - 100%
    wp_conf = calculate_confidence_score(DiscoverySource.WORDPRESS_INDEX, 200, "application/json")
    assert wp_conf >= 98

    # JavaScript bundle + 401 Auth -> high confidence that endpoint exists
    js_conf = calculate_confidence_score(DiscoverySource.JAVASCRIPT_BUNDLE, 401, "application/json")
    assert js_conf >= 80

    # Standard Guess + 404 -> very low confidence
    guess_conf = calculate_confidence_score(DiscoverySource.STANDARD_GUESS, 404, "text/html")
    assert guess_conf <= 20


def test_classify_service():
    name, cat, summary = classify_service("/wp-json/wp/v2/posts", "application/json", 200)
    assert name == "WordPress Posts Feed"
    assert cat == "CMS & Content"

    name2, cat2, _ = classify_service("/graphql", "application/json", 200)
    assert name2 == "GraphQL Query Gateway"
    assert cat2 == "Data Gateway"


@pytest.mark.asyncio
async def test_discover_website_apis_endpoint(client: AsyncClient, monkeypatch):
    from unittest.mock import AsyncMock

    mock_report = WebsiteApiReport(
        target_url="https://example.com",
        normalized_base="https://example.com",
        scanned_at=1700000000.0,
        server_header="nginx/1.24",
        total_endpoints=1,
        discovered_endpoints_count=1,
        probed_guesses_count=0,
        online_count=1,
        protected_count=0,
        shielded_count=0,
        not_found_count=0,
        avg_latency_ms=88.5,
        endpoints=[
            EndpointIntelligence(
                url="https://example.com/wp-json/wp/v2/posts",
                path="/wp-json/wp/v2/posts",
                method="GET",
                service_name="WordPress Posts Feed",
                category="CMS & Content",
                source_type=DiscoverySource.WORDPRESS_INDEX,
                confidence_score=99,
                status_code=200,
                availability=EndpointAvailability.ONLINE,
                accessibility=EndpointAccessibility.OPEN,
                is_open=True,
                requires_auth=False,
                is_restricted=False,
                response_time_ms=88.5,
                content_type="application/json",
                summary="Public stream of articles"
            )
        ]
    )

    monkeypatch.setattr(
        "app.routers.apis.extract_and_analyze_website_apis",
        AsyncMock(return_value=mock_report)
    )

    res = await client.post("/apis/discover-website-apis", json={"url": "https://example.com"})
    assert res.status_code == 200
    data = res.json()
    assert data["total_endpoints"] == 1
    assert data["online_count"] == 1
    assert data["endpoints"][0]["service_name"] == "WordPress Posts Feed"
    assert data["endpoints"][0]["confidence_score"] == 99
    assert data["endpoints"][0]["source_type"] == "WORDPRESS_INDEX"
