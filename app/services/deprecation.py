import hashlib
import re
from typing import List, Optional, Tuple

from app.models.tracked_api import TrackedAPI

DEPRECATION_KEYWORDS = [
    r"\bdeprecated\b",
    r"\bsunset\b",
    r"\bwill be removed\b",
    r"\bend of life\b",
    r"\beol\b",
    r"\bdiscontinued\b",
    r"\bbreaking change\b",
    r"\bdecommission(ed)?\b"
]

KEYWORD_REGEX = re.compile("|".join(DEPRECATION_KEYWORDS), re.IGNORECASE)


def compute_content_hash(content: str) -> str:
    """Computes SHA-256 hex digest of page content."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def extract_deprecation_mentions(content: str, max_excerpts: int = 5) -> List[str]:
    """Finds sentences or paragraphs matching deprecation keywords."""
    excerpts: List[str] = []
    # Split content into paragraphs / lines
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\.\s+", content) if p.strip()]

    for p in paragraphs:
        if KEYWORD_REGEX.search(p):
            # Clean excessive whitespace
            clean_text = " ".join(p.split())
            if clean_text not in excerpts:
                excerpts.append(clean_text)
                if len(excerpts) >= max_excerpts:
                    break

    return excerpts


async def summarize_deprecation_with_llm(extracted_text: str) -> Optional[str]:
    """Optional extension hook: Pass flagged deprecation text to an LLM for structured summary.
    
    In v1, this returns None unless an LLM provider is explicitly configured.
    """
    # Prepared extension point for OpenAI/Anthropic SDK
    return None


def inspect_changelog(
    tracked_api: TrackedAPI,
    current_content: str
) -> Tuple[bool, str, List[str]]:
    """Evaluates changelog content for updates and extracts deprecation keywords.
    
    Returns: (has_changed, current_hash, matching_excerpts)
    """
    current_hash = compute_content_hash(current_content)
    has_changed = (tracked_api.last_changelog_hash != current_hash)
    matches: List[str] = []

    if has_changed:
        matches = extract_deprecation_mentions(current_content)

    return has_changed, current_hash, matches


async def auto_probe_changelog_url(
    base_url: str,
    response_headers: Optional[dict] = None,
    client: Optional[Any] = None
) -> Optional[str]:
    """Automatically probes and discovers API documentation or changelog URLs."""
    import httpx

    # 1. Check Link header
    if response_headers:
        link_header = response_headers.get("link", "")
        if "rel=\"help\"" in link_header or "rel=\"documentation\"" in link_header:
            m = re.search(r'<([^>]+)>;\s*rel="(?:help|documentation)"', link_header, re.IGNORECASE)
            if m:
                return m.group(1)

    # 2. Probe common paths on base host
    clean_base = base_url.rstrip("/")
    candidates = [f"{clean_base}/changelog", f"{clean_base}/docs", f"{clean_base}/api-docs"]

    should_close = False
    if client is None:
        client = httpx.AsyncClient(
            timeout=3.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        should_close = True

    try:
        for candidate in candidates:
            try:
                resp = await client.head(candidate, follow_redirects=True)
                if resp.status_code == 200:
                    return candidate
                if resp.status_code in (401, 403):
                    # CDN or host blocks speculative HEAD requests; abort immediately to avoid IP threat score increase
                    break
            except Exception:
                pass
    finally:
        if should_close:
            await client.aclose()

    return None
