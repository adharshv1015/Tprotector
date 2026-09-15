from app.models.tracked_api import TrackedAPI
from app.services.rate_limit import extract_rate_limit


def test_standard_rate_limit_headers():
    api = TrackedAPI(
        name="GitHub",
        base_url="https://api.github.com",
        endpoint_path="/",
        rate_limit_header_limit="X-RateLimit-Limit",
        rate_limit_header_remaining="X-RateLimit-Remaining",
        rate_limit_header_reset="X-RateLimit-Reset"
    )

    headers = {
        "x-ratelimit-limit": "5000",
        "x-ratelimit-remaining": "500",
        "x-ratelimit-reset": "1720000000"
    }

    limit, remaining, reset, usage_pct, is_warning = extract_rate_limit(
        headers=headers,
        tracked_api=api,
        threshold=80.0
    )

    assert limit == 5000
    assert remaining == 500
    assert reset == "1720000000"
    assert usage_pct == 90.0
    assert is_warning is True


def test_rate_limit_below_threshold():
    api = TrackedAPI(name="Stripe", base_url="https://api.stripe.com", endpoint_path="/")
    headers = {
        "x-ratelimit-limit": "100",
        "x-ratelimit-remaining": "85"
    }

    limit, remaining, reset, usage_pct, is_warning = extract_rate_limit(
        headers=headers,
        tracked_api=api,
        threshold=80.0
    )

    assert limit == 100
    assert remaining == 85
    assert usage_pct == 15.0
    assert is_warning is False


def test_missing_rate_limit_headers():
    api = TrackedAPI(name="Generic", base_url="https://api.example.com", endpoint_path="/")
    headers = {"content-type": "application/json"}

    limit, remaining, reset, usage_pct, is_warning = extract_rate_limit(
        headers=headers,
        tracked_api=api
    )

    assert limit is None
    assert remaining is None
    assert usage_pct is None
    assert is_warning is False
