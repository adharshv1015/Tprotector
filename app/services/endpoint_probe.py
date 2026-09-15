import asyncio
import logging
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from app.services.ssrf_protection import SSRFValidationError, validate_target_url
from app.services.website_crawler import BROWSER_HEADERS

logger = logging.getLogger(__name__)


class ProbeResult(BaseModel):
    url: str
    path: str
    status_code: int
    response_time_ms: float
    content_type: str
    headers: Dict[str, str]


async def probe_candidates_concurrently(
    candidate_urls: List[str],
    max_concurrency: int = 6,
    timeout_seconds: float = 6.0
) -> List[ProbeResult]:
    """Concurrently probes candidate endpoints with SSRF guards and precise latency measurement."""
    semaphore = asyncio.Semaphore(max_concurrency)
    results: List[ProbeResult] = []

    async def probe_single(u: str) -> Optional[ProbeResult]:
        async with semaphore:
            try:
                # SSRF guard on every probed candidate URL
                validate_target_url(u)
            except SSRFValidationError:
                return None

            p = urlparse(u)
            path = p.path or "/"
            if p.query:
                path += f"?{p.query}"

            probe_headers = {
                **BROWSER_HEADERS,
                "Referer": f"{p.scheme}://{p.netloc}/",
                "Origin": f"{p.scheme}://{p.netloc}",
            }

            start = time.perf_counter()
            try:
                async with httpx.AsyncClient(
                    timeout=timeout_seconds,
                    headers=probe_headers,
                    follow_redirects=True
                ) as client:
                    resp = await client.get(u)
                    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
                    ct = resp.headers.get("content-type", "unknown").split(";")[0].strip()

                    return ProbeResult(
                        url=u,
                        path=path,
                        status_code=resp.status_code,
                        response_time_ms=elapsed_ms,
                        content_type=ct,
                        headers=dict(resp.headers)
                    )
            except Exception:
                return None

    probed = await asyncio.gather(*(probe_single(url) for url in candidate_urls))
    for res in probed:
        if res is not None:
            results.append(res)

    return results
