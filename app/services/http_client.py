import asyncio
import base64
import logging
import time
from typing import Any, Dict, Optional, Tuple
import httpx

from app.config import settings
from app.models.tracked_api import AuthType, HttpMethod, TrackedAPI
from app.services.encryption import decrypt_secret

logger = logging.getLogger(__name__)

# In-memory OAuth2 token cache: {api_id: (access_token, expires_at_timestamp)}
_oauth2_token_cache: Dict[int, Tuple[str, float]] = {}


async def resolve_auth_headers(tracked_api: TrackedAPI) -> Dict[str, str]:
    """Decrypts auth_config and constructs necessary authentication headers."""
    if tracked_api.auth_type == AuthType.NONE or not tracked_api.auth_config:
        return {}

    try:
        config = decrypt_secret(tracked_api.auth_config)
    except Exception as e:
        logger.error(f"Failed to decrypt auth_config for API {tracked_api.id}: {e}")
        return {}

    headers: Dict[str, str] = {}

    if tracked_api.auth_type == AuthType.BEARER:
        token = config.get("token") or config.get("bearer_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

    elif tracked_api.auth_type == AuthType.API_KEY:
        header_name = config.get("header_name", "X-API-Key")
        api_key = config.get("api_key") or config.get("key")
        if api_key:
            headers[header_name] = api_key

    elif tracked_api.auth_type == AuthType.BASIC:
        username = config.get("username", "")
        password = config.get("password", "")
        auth_str = f"{username}:{password}".encode("utf-8")
        encoded = base64.b64encode(auth_str).decode("utf-8")
        headers["Authorization"] = f"Basic {encoded}"

    elif tracked_api.auth_type == AuthType.OAUTH2_CLIENT_CREDENTIALS:
        token = await get_oauth2_token(tracked_api.id, config)
        if token:
            headers["Authorization"] = f"Bearer {token}"

    return headers


async def get_oauth2_token(api_id: int, config: Dict[str, Any]) -> Optional[str]:
    """Retrieves a cached OAuth2 client credentials token, or requests a new one if expired."""
    now = time.time()
    cached = _oauth2_token_cache.get(api_id)
    if cached:
        token, expires_at = cached
        if expires_at - now > 60:  # 60-second safety buffer
            return token

    token_url = config.get("token_url")
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    scope = config.get("scope")

    if not token_url or not client_id or not client_secret:
        logger.error(f"Incomplete OAuth2 configuration for API ID {api_id}")
        return None

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        data["scope"] = scope

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code == 200:
                body = resp.json()
                access_token = body.get("access_token")
                expires_in = body.get("expires_in", 3600)
                _oauth2_token_cache[api_id] = (access_token, now + float(expires_in))
                return access_token
            else:
                logger.error(f"OAuth2 token request failed with status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Exception during OAuth2 token retrieval: {e}")

    return None


async def execute_monitored_request(
    tracked_api: TrackedAPI,
    max_retries: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None
) -> Tuple[Optional[httpx.Response], float, Optional[str]]:
    """Executes a monitored API check with automatic retry and exponential backoff.
    
    Retry invariant: Retries happen internally before returning a single outcome.
    Returns: (response, response_time_ms, error_message)
    """
    retries = max_retries if max_retries is not None else settings.HTTP_MAX_RETRIES
    url = f"{tracked_api.base_url.rstrip('/')}/{tracked_api.endpoint_path.lstrip('/')}"
    
    # Headers (use modern browser UA to avoid CDN bot firewall blocks like Cloudflare/Hostinger CDN)
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    }
    if tracked_api.custom_headers:
        for k, v in tracked_api.custom_headers.items():
            # Never allow legacy bot agent saved in database to overwrite browser UA
            if k.lower() == "user-agent" and any(b in str(v).lower() for b in ["aegis-observer", "apimonitor-agent", "python-httpx"]):
                continue
            req_headers[k] = v
    auth_headers = await resolve_auth_headers(tracked_api)
    req_headers.update(auth_headers)

    method = tracked_api.method.value if isinstance(tracked_api.method, HttpMethod) else str(tracked_api.method)
    payload = tracked_api.test_payload if method in ("POST", "PUT", "PATCH") else None

    last_error: Optional[str] = None
    last_response: Optional[httpx.Response] = None
    total_elapsed_ms: float = 0.0

    should_close_client = False
    if client is None:
        client = httpx.AsyncClient(
            timeout=settings.HTTP_REQUEST_TIMEOUT_SECONDS,
            headers=req_headers,
            follow_redirects=True
        )
        should_close_client = True

    try:
        for attempt in range(1, retries + 1):
            start_time = time.perf_counter()
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    json=payload,
                    follow_redirects=True
                )
                elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                total_elapsed_ms = elapsed_ms
                last_response = response

                # Consider 5xx a retryable server error if attempts remain
                if response.status_code >= 500 and attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue

                return response, elapsed_ms, None

            except (httpx.RequestError, asyncio.TimeoutError) as exc:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                total_elapsed_ms = elapsed_ms
                last_error = f"{type(exc).__name__}: {str(exc)}"
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue

        return last_response, total_elapsed_ms, last_error

    finally:
        if should_close_client:
            await client.aclose()
