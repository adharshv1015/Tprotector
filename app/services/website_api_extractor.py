import logging
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel

from app.services.endpoint_probe import ProbeResult, probe_candidates_concurrently
from app.services.service_classifier import (
    DiscoverySource,
    EndpointAccessibility,
    EndpointAvailability,
    calculate_confidence_score,
    classify_service,
    evaluate_endpoint_status,
)
from app.services.ssrf_protection import validate_target_url
from app.services.website_crawler import BROWSER_HEADERS, crawl_website_assets

logger = logging.getLogger(__name__)


class EndpointIntelligence(BaseModel):
    url: str
    path: str
    method: str = "GET"
    service_name: str
    category: str
    source_type: DiscoverySource
    confidence_score: int
    status_code: int
    availability: EndpointAvailability
    accessibility: EndpointAccessibility
    is_open: bool
    requires_auth: bool
    is_restricted: bool
    response_time_ms: float
    content_type: str
    summary: str


class WebsiteApiReport(BaseModel):
    target_url: str
    normalized_base: str
    scanned_at: float
    server_header: Optional[str] = None
    total_endpoints: int
    discovered_endpoints_count: int
    probed_guesses_count: int
    online_count: int
    protected_count: int
    shielded_count: int
    not_found_count: int
    avg_latency_ms: float
    endpoints: List[EndpointIntelligence]


async def extract_and_analyze_website_apis(target_input: str) -> WebsiteApiReport:
    """Discovers, validates, classifies, and benchmarks all APIs on a website.
    
    Modular pipeline:
    1. SSRF URL Validation
    2. Crawler (HTML + Bounded Same-Origin JS assets)
    3. Multi-Source Endpoint Discovery (HTML Link, JS bundle, WP-JSON route index, standard guesses)
    4. Concurrent HTTP Probing
    5. Service Intelligence & Confidence Scoring
    """
    safe_url = validate_target_url(target_input)
    parsed = urlparse(safe_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    start_time = time.time()

    # Tracking candidates with their discovery source
    # url -> DiscoverySource
    candidates: Dict[str, DiscoverySource] = {}

    # 1. Crawl website HTML and same-origin JS
    root_html, js_scripts, server_header = await crawl_website_assets(safe_url)

    # 2. Extract from HTML <link> tags
    wp_link_match = re.search(r'<link[^>]+rel=["\']https://api\.w\.org/["\'][^>]+href=["\']([^"\']+)["\']', root_html, re.IGNORECASE)
    if not wp_link_match:
        wp_link_match = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']https://api\.w\.org/["\']', root_html, re.IGNORECASE)
    if wp_link_match:
        wp_root = wp_link_match.group(1).rstrip("/") + "/"
        candidates[wp_root] = DiscoverySource.HTML_LINK

    for m in re.finditer(r'<link[^>]+type=["\'](?:application/json\+oembed|application/rss\+xml)["\'][^>]+href=["\']([^"\']+)["\']', root_html, re.IGNORECASE):
        candidates[m.group(1)] = DiscoverySource.HTML_LINK

    # 3. Deep WordPress Route Directory Enumeration (/wp-json/)
    wp_json_url = urljoin(base_url, "/wp-json/")
    wp_headers = {
        **BROWSER_HEADERS,
        "Referer": f"{base_url}/",
        "Origin": base_url,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=wp_headers, follow_redirects=True) as wp_client:
            wp_resp = await wp_client.get(wp_json_url)
            if wp_resp.status_code == 200 and "json" in wp_resp.headers.get("content-type", "").lower():
                candidates[wp_json_url] = DiscoverySource.WORDPRESS_INDEX
                wp_data = wp_resp.json()
                routes = wp_data.get("routes", {})
                for route_path in list(routes.keys()):
                    # Skip parameterized regex templates like (?P<id>[\d]+)
                    if any(c in route_path for c in "()<>[];"):
                        continue
                    # Prioritize core v2 content routes and custom plugin namespaces
                    if route_path.startswith(("/wp/v2/", "/custom/", "/api/")):
                        full_route_url = urljoin(wp_json_url, route_path.lstrip("/"))
                        candidates[full_route_url] = DiscoverySource.WORDPRESS_INDEX
    except Exception:
        pass

    # 4. Extract from JavaScript (inline HTML scripts + downloaded external same-origin JS)
    all_scripts = [root_html] + js_scripts
    for script_text in all_scripts:
        # fetch() / axios calls
        for m in re.finditer(r'(?:fetch|axios\.(?:get|post|put|delete)|\$\.ajax)\s*\(\s*[\'"`](/[a-zA-Z0-9_\-\./?&=]+)[\'"`]', script_text):
            ep_path = m.group(1)
            if not ep_path.endswith((".css", ".png", ".jpg", ".svg", ".ico", ".woff")):
                candidates[urljoin(base_url, ep_path)] = DiscoverySource.JAVASCRIPT_BUNDLE

        # generic /api/ occurrences in JS
        for m in re.finditer(r'[\'"`](/(?:api|v[1-3]|graphql|service)[a-zA-Z0-9_\-\./?&=]*)[\'"`]', script_text):
            ep_path = m.group(1)
            if not ep_path.endswith((".css", ".png", ".jpg", ".js")):
                candidates[urljoin(base_url, ep_path)] = DiscoverySource.JAVASCRIPT_BUNDLE

    # Check if target website genuinely uses WordPress
    is_wordpress = (
        bool(wp_link_match)
        or any(c == DiscoverySource.WORDPRESS_INDEX for c in candidates.values())
        or "wp-content" in root_html
        or "wp-includes" in root_html
    )

    # 5. Add standard guessed candidate paths
    standard_guesses = [
        "/api",
        "/api/v1",
        "/api/health",
        "/health",
        "/graphql",
        "/feed",
        "/sitemap.xml",
        "/robots.txt",
    ]
    if is_wordpress:
        standard_guesses = [
            "/wp-json/wp/v2/posts",
            "/wp-json/wp/v2/pages",
            "/wp-json/wp/v2/media",
        ] + standard_guesses

    for sp in standard_guesses:
        full_u = urljoin(base_url, sp)
        if full_u not in candidates:
            candidates[full_u] = DiscoverySource.STANDARD_GUESS

    # 6. Concurrently probe candidates (capped at 25 endpoints)
    candidate_urls = list(candidates.keys())[:25]
    probed_results: List[ProbeResult] = await probe_candidates_concurrently(candidate_urls)

    # Map probe results to URL
    probe_map = {res.url: res for res in probed_results}

    # 7. Classify & score each endpoint
    endpoint_intelligences: List[EndpointIntelligence] = []
    total_latency = 0.0

    for u in candidate_urls:
        res = probe_map.get(u)
        if not res:
            continue

        source = candidates.get(u, DiscoverySource.STANDARD_GUESS)

        # Discard dead guesses (404s, or WordPress guesses on non-WordPress sites)
        if source == DiscoverySource.STANDARD_GUESS:
            if res.status_code == 404:
                continue
            if not is_wordpress and "/wp-json/" in res.path:
                continue

        availability, accessibility = evaluate_endpoint_status(res.status_code)
        conf_score = calculate_confidence_score(source, res.status_code, res.content_type)
        srv_name, cat, summary = classify_service(res.path, res.content_type, res.status_code)

        is_open = (accessibility == EndpointAccessibility.OPEN)
        requires_auth = (accessibility == EndpointAccessibility.PROTECTED)
        is_restricted = (accessibility in (EndpointAccessibility.SHIELDED, EndpointAccessibility.METHOD_RESTRICTED))

        total_latency += res.response_time_ms

        endpoint_intelligences.append(
            EndpointIntelligence(
                url=res.url,
                path=res.path,
                method="GET",
                service_name=srv_name,
                category=cat,
                source_type=source,
                confidence_score=conf_score,
                status_code=res.status_code,
                availability=availability,
                accessibility=accessibility,
                is_open=is_open,
                requires_auth=requires_auth,
                is_restricted=is_restricted,
                response_time_ms=res.response_time_ms,
                content_type=res.content_type,
                summary=summary
            )
        )

    # Sort endpoints: Highest confidence & online status first, then lowest latency
    endpoint_intelligences.sort(
        key=lambda e: (
            0 if e.availability == EndpointAvailability.ONLINE else 1,
            -e.confidence_score,
            e.response_time_ms
        )
    )

    total_ep = len(endpoint_intelligences)
    discovered_count = sum(1 for e in endpoint_intelligences if e.source_type != DiscoverySource.STANDARD_GUESS)
    probed_count = sum(1 for e in endpoint_intelligences if e.source_type == DiscoverySource.STANDARD_GUESS)
    online_count = sum(1 for e in endpoint_intelligences if e.accessibility == EndpointAccessibility.OPEN)
    protected_count = sum(1 for e in endpoint_intelligences if e.accessibility == EndpointAccessibility.PROTECTED)
    shielded_count = sum(1 for e in endpoint_intelligences if e.accessibility in (EndpointAccessibility.SHIELDED, EndpointAccessibility.METHOD_RESTRICTED))
    not_found_count = sum(1 for e in endpoint_intelligences if e.availability == EndpointAvailability.NOT_FOUND)
    avg_latency = round(total_latency / total_ep, 1) if total_ep > 0 else 0.0

    return WebsiteApiReport(
        target_url=safe_url,
        normalized_base=base_url,
        scanned_at=start_time,
        server_header=server_header,
        total_endpoints=total_ep,
        discovered_endpoints_count=discovered_count,
        probed_guesses_count=probed_count,
        online_count=online_count,
        protected_count=protected_count,
        shielded_count=shielded_count,
        not_found_count=not_found_count,
        avg_latency_ms=avg_latency,
        endpoints=endpoint_intelligences
    )
