from enum import Enum
from typing import Tuple


class EndpointAvailability(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    NOT_FOUND = "NOT_FOUND"


class EndpointAccessibility(str, Enum):
    OPEN = "OPEN"
    PROTECTED = "PROTECTED"
    SHIELDED = "SHIELDED"
    METHOD_RESTRICTED = "METHOD_RESTRICTED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    NOT_FOUND = "NOT_FOUND"


class DiscoverySource(str, Enum):
    WORDPRESS_INDEX = "WORDPRESS_INDEX"
    HTML_LINK = "HTML_LINK"
    JAVASCRIPT_BUNDLE = "JAVASCRIPT_BUNDLE"
    STANDARD_GUESS = "STANDARD_GUESS"


def evaluate_endpoint_status(status_code: int) -> Tuple[EndpointAvailability, EndpointAccessibility]:
    """Evaluates availability vs accessibility to distinguish functioning but protected APIs from broken ones."""
    if status_code in (200, 201, 204):
        return EndpointAvailability.ONLINE, EndpointAccessibility.OPEN
    elif status_code == 401:
        # 401 is strong evidence the API exists and requires credentials
        return EndpointAvailability.ONLINE, EndpointAccessibility.PROTECTED
    elif status_code == 403:
        # 403 indicates resource exists but is forbidden or behind CDN firewall
        return EndpointAvailability.ONLINE, EndpointAccessibility.SHIELDED
    elif status_code == 405:
        # 405 indicates endpoint exists but requires a different HTTP method (e.g. POST)
        return EndpointAvailability.ONLINE, EndpointAccessibility.METHOD_RESTRICTED
    elif status_code == 429:
        return EndpointAvailability.DEGRADED, EndpointAccessibility.RATE_LIMITED
    elif status_code == 404:
        return EndpointAvailability.NOT_FOUND, EndpointAccessibility.NOT_FOUND
    elif status_code >= 500:
        return EndpointAvailability.OFFLINE, EndpointAccessibility.SERVER_ERROR
    else:
        return EndpointAvailability.ONLINE, EndpointAccessibility.OPEN


def calculate_confidence_score(
    source_type: DiscoverySource,
    status_code: int,
    content_type: str
) -> int:
    """Calculates an endpoint confidence score (0 - 100%) based on source attribution and HTTP response."""
    score = 50

    # Source credibility
    if source_type == DiscoverySource.WORDPRESS_INDEX:
        score = 98  # Registered in official schema
    elif source_type == DiscoverySource.HTML_LINK:
        score = 94  # Declared in HTML link header
    elif source_type == DiscoverySource.JAVASCRIPT_BUNDLE:
        score = 80  # Extracted from client-side JS
    elif source_type == DiscoverySource.STANDARD_GUESS:
        score = 45  # Speculative candidate probe

    # Response verification adjustments
    if status_code in (200, 201):
        score = min(100, score + 10)
        if "json" in content_type.lower() or "xml" in content_type.lower():
            score = min(100, score + 5)
    elif status_code in (401, 405):
        # Authenticated or method restricted confirms endpoint existence
        score = min(95, score + 8)
    elif status_code == 403:
        # Cloudflare/CDN shield or restricted admin route
        score = min(85, score)
    elif status_code == 404:
        # Failed speculative guesses drop sharply
        if source_type == DiscoverySource.STANDARD_GUESS:
            score = 15
        else:
            score = max(30, score - 30)

    return max(5, min(100, score))


def classify_service(path: str, content_type: str, status_code: int) -> Tuple[str, str, str]:
    """Infers (service_name, category, summary) from endpoint path and characteristics."""
    p_lower = path.lower()

    if "/wp-json/wp/v2/posts" in p_lower:
        return "WordPress Posts Feed", "CMS & Content", "Public stream of articles, blog posts, and published content"
    if "/wp-json/wp/v2/pages" in p_lower:
        return "WordPress Pages Feed", "CMS & Content", "Public index of static site pages and structure"
    if "/wp-json/wp/v2/media" in p_lower:
        return "WordPress Media Library", "Assets & Media", "Asset metadata, images, and upload registry"
    if "/wp-json/wp/v2/categories" in p_lower:
        return "Taxonomy & Categories", "Taxonomy", "Taxonomy hierarchy and topic tagging directory"
    if "/wp-json/wp/v2/users" in p_lower:
        return "WordPress Authors / Users", "Identity & Auth", "Public author profiles and user contributors"
    if "/wp-json/wp/v2/comments" in p_lower:
        return "WordPress Comments Feed", "CMS & Content", "Public reader comments and feedback threads"
    if "/wp-json" in p_lower and len(path.strip("/").split("/")) <= 2:
        return "WordPress REST Registry", "Core Gateway", "Root schema directory enumerating all installed API routes"
    if "graphql" in p_lower:
        return "GraphQL Query Gateway", "Data Gateway", "Unified GraphQL API query and mutation endpoint"
    if any(h in p_lower for h in ["health", "healthz", "status", "ping"]):
        return "System Healthcheck", "DevOps & Monitoring", "Operational uptime and readiness heartbeat probe"
    if any(a in p_lower for a in ["auth", "login", "token", "oauth", "session", "user", "me"]):
        return "Authentication Service", "Identity & Security", "Session management and credential verification gateway"
    if any(f in p_lower for f in ["feed", "rss", "atom"]):
        return "Syndication RSS Feed", "Feeds & Syndication", "XML/RSS data stream for content subscribers and aggregators"
    if "sitemap" in p_lower:
        return "Sitemap XML Index", "SEO & Discovery", "Index of canonical URLs for search engines and crawlers"
    if "openapi" in p_lower or "swagger" in p_lower:
        return "API Documentation / Schema", "Developer Docs", "Machine-readable OpenAPI/Swagger contract definition"

    clean_slug = path.strip("/").replace("/", " ").replace("-", " ").replace("_", " ").title()
    name = f"Service ({clean_slug})" if clean_slug else "Root Service"
    cat = "REST API" if "json" in content_type.lower() else "Web Endpoint"
    return name, cat, f"Service endpoint at {path}"
