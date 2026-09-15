from typing import Any, Dict, Optional, Tuple

from app.config import settings
from app.models.tracked_api import TrackedAPI


def auto_discover_rate_limit_headers(
    headers: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Automatically identifies rate-limiting header patterns from any API response.
    
    Checks standard RFC, GitHub/Stripe/Shopify/Twitter conventions, or any integer header
    ending in 'limit'/'remaining'/'reset'.
    """
    header_keys = list(headers.keys())
    lower_map = {k.lower(): k for k in header_keys}

    # Known standard triplets (ordered by popularity)
    known_triplets = [
        ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"),
        ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"),
        ("x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset"),
        ("x-ratelimit-limit-minute", "x-ratelimit-remaining-minute", "x-ratelimit-reset-minute"),
    ]

    for limit_candidate, rem_candidate, reset_candidate in known_triplets:
        if limit_candidate in lower_map and rem_candidate in lower_map:
            return (
                lower_map[limit_candidate],
                lower_map[rem_candidate],
                lower_map.get(reset_candidate)
            )

    # Heuristic dynamic scan for any custom pair
    detected_limit = None
    detected_rem = None
    detected_reset = None

    for low_k, original_k in lower_map.items():
        if "limit" in low_k and "remaining" not in low_k and "reset" not in low_k:
            if str(headers[original_k]).strip().isdigit():
                detected_limit = original_k
        elif "remaining" in low_k:
            if str(headers[original_k]).strip().isdigit():
                detected_rem = original_k
        elif "reset" in low_k:
            detected_reset = original_k

    if detected_limit and detected_rem:
        return detected_limit, detected_rem, detected_reset

    return None, None, None


def extract_rate_limit(
    headers: Dict[str, Any],
    tracked_api: TrackedAPI,
    threshold: Optional[float] = None
) -> Tuple[Optional[int], Optional[int], Optional[str], Optional[float], bool]:
    """Inspects response headers for rate limit counters and computes usage percentage.
    
    If headers are not configured on the tracked API, automatically probes and discovers them!
    Returns: (limit_val, remaining_val, reset_val, usage_percent, is_warning)
    """
    threshold = threshold if threshold is not None else settings.DEFAULT_RATE_LIMIT_THRESHOLD
    headers_lower = {k.lower(): str(v) for k, v in headers.items()}

    limit_key = (tracked_api.rate_limit_header_limit or "").lower()
    remaining_key = (tracked_api.rate_limit_header_remaining or "").lower()
    reset_key = (tracked_api.rate_limit_header_reset or "").lower()

    # Automatic discovery fallback if not configured
    if not limit_key or not remaining_key:
        auto_limit, auto_rem, auto_reset = auto_discover_rate_limit_headers(headers)
        if auto_limit and auto_rem:
            limit_key = auto_limit.lower()
            remaining_key = auto_rem.lower()
            reset_key = (auto_reset or "").lower()

    # Fallback to standard conventions if still not matched
    if limit_key not in headers_lower and "x-ratelimit-limit" in headers_lower:
        limit_key = "x-ratelimit-limit"
    if remaining_key not in headers_lower and "x-ratelimit-remaining" in headers_lower:
        remaining_key = "x-ratelimit-remaining"
    if reset_key not in headers_lower and "x-ratelimit-reset" in headers_lower:
        reset_key = "x-ratelimit-reset"

    limit_val: Optional[int] = None
    remaining_val: Optional[int] = None
    reset_val: Optional[str] = headers_lower.get(reset_key)

    if limit_key in headers_lower:
        try:
            limit_val = int(headers_lower[limit_key])
        except (ValueError, TypeError):
            pass

    if remaining_key in headers_lower:
        try:
            remaining_val = int(headers_lower[remaining_key])
        except (ValueError, TypeError):
            pass

    usage_percent: Optional[float] = None
    is_warning = False

    if limit_val is not None and remaining_val is not None and limit_val > 0:
        usage_percent = round((1.0 - (remaining_val / limit_val)) * 100.0, 2)
        if usage_percent >= threshold:
            is_warning = True

    return limit_val, remaining_val, reset_val, usage_percent, is_warning
