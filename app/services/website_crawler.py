import asyncio
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from app.services.ssrf_protection import validate_target_url

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}

MAX_JS_SCRIPTS = 5  # Strict limit to avoid uncontrolled crawler runaways
MAX_JS_SIZE_BYTES = 300_000  # Max 300KB per script


async def crawl_website_assets(target_url: str) -> Tuple[str, List[str], Optional[str]]:
    """Crawls website root HTML and downloads same-origin JavaScript files (bounded).
    
    Returns: (root_html, list_of_js_script_contents, server_header)
    """
    safe_url = validate_target_url(target_url)
    parsed = urlparse(safe_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    root_html = ""
    server_header: Optional[str] = None
    js_contents: List[str] = []

    async with httpx.AsyncClient(timeout=10.0, headers=BROWSER_HEADERS, follow_redirects=True) as client:
        try:
            resp = await client.get(safe_url)
            server_header = resp.headers.get("server")
            root_html = resp.text
        except Exception as exc:
            logger.warning(f"Failed to fetch HTML for {safe_url}: {exc}")
            return "", [], None

        # Extract same-origin <script src="...">
        script_srcs: List[str] = []
        for m in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', root_html, re.IGNORECASE):
            src = m.group(1).strip()
            # Ignore third-party analytics / ads scripts (google, facebook, hotjar, etc.)
            if any(ign in src.lower() for ign in ["google", "facebook", "gtag", "analytics", "hotjar", "clarity", "sentry"]):
                continue

            full_script_url = urljoin(base_url, src)
            script_parsed = urlparse(full_script_url)
            # Ensure same origin and safe URL
            if script_parsed.netloc.lower() == parsed.netloc.lower():
                if full_script_url not in script_srcs:
                    script_srcs.append(full_script_url)

        # Bounded concurrent download of top same-origin scripts
        scripts_to_fetch = script_srcs[:MAX_JS_SCRIPTS]

        async def fetch_js(js_url: str) -> Optional[str]:
            try:
                validate_target_url(js_url)
                r = await client.get(js_url)
                if r.status_code == 200 and len(r.content) <= MAX_JS_SIZE_BYTES:
                    return r.text
            except Exception:
                pass
            return None

        fetched = await asyncio.gather(*(fetch_js(u) for u in scripts_to_fetch))
        for content in fetched:
            if content:
                js_contents.append(content)

    return root_html, js_contents, server_header
