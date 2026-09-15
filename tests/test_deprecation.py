from app.models.tracked_api import TrackedAPI
from app.services.deprecation import (
    compute_content_hash,
    extract_deprecation_mentions,
    inspect_changelog,
)


def test_changelog_hash_and_keywords():
    api = TrackedAPI(
        name="Payment Gateway",
        base_url="https://api.gateway.com",
        endpoint_path="/v1",
        changelog_url="https://docs.gateway.com/changelog",
        last_changelog_hash="old_known_hash_value"
    )

    page_content = """
    # API Changelog v2.4
    
    We have introduced new features in this release.
    
    Please note: The /v1/tokens endpoint is deprecated and will be removed in December 2026.
    
    All developers should migrate to the /v2/tokens endpoint immediately.
    """

    has_changed, new_hash, matches = inspect_changelog(api, page_content)

    assert has_changed is True
    assert new_hash != "old_known_hash_value"
    assert len(matches) >= 1
    assert any("deprecated" in m.lower() for m in matches)


def test_unchanged_changelog_returns_no_change():
    content = "Static changelog text."
    current_hash = compute_content_hash(content)

    api = TrackedAPI(
        name="Static Docs",
        base_url="https://api.example.com",
        endpoint_path="/",
        last_changelog_hash=current_hash
    )

    has_changed, new_hash, matches = inspect_changelog(api, content)
    assert has_changed is False
    assert matches == []
