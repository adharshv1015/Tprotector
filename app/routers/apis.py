from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.snapshot import ApiSnapshot
from app.models.tracked_api import ApiStatus, AuthType, HttpMethod, TrackedAPI
from app.schemas.snapshot import ApiSnapshotResponse
from app.schemas.tracked_api import (
    TrackedAPICreate,
    TrackedAPIResponse,
    TrackedAPIUpdate,
)
import time
from urllib.parse import urlparse
from pydantic import BaseModel, Field
from app.scheduler.bootstrap import remove_api_job, schedule_api_job
from app.scheduler.runner import run_full_check
from app.services.deprecation import auto_probe_changelog_url
from app.services.encryption import encrypt_secret
from app.services.rate_limit import auto_discover_rate_limit_headers
from app.services.schema_diff import extract_schema
import httpx

router = APIRouter(prefix="/apis", tags=["Tracked APIs"])


class AutoProbeRequest(BaseModel):
    url: str = Field(..., description="Full API URL to probe e.g. https://api.github.com/zen")
    method: HttpMethod = Field(default=HttpMethod.GET)
    auth_token: Optional[str] = Field(default=None, description="Optional Bearer token or API key")


class AutoTrackRequest(BaseModel):
    url: str = Field(..., description="Full API URL to auto-track")
    name: Optional[str] = None
    method: HttpMethod = Field(default=HttpMethod.GET)
    auth_token: Optional[str] = None
    is_sandbox: bool = False
    session_id: Optional[str] = None
    check_interval_minutes: Optional[int] = Field(default=None, ge=1)


from app.services.universal_scanner import resolve_api_input
from app.services.website_api_extractor import extract_and_analyze_website_apis, WebsiteApiReport


class WebsiteDiscoveryRequest(BaseModel):
    url: str = Field(..., description="Website URL to extract and analyze APIs from")


@router.post("/discover-website-apis", response_model=WebsiteApiReport)
async def discover_website_apis_endpoint(req: WebsiteDiscoveryRequest):
    """Deep crawl of target website to extract, analyze, and report all discovered API endpoints and services."""
    return await extract_and_analyze_website_apis(req.url)


@router.post("/auto-probe")
async def auto_probe_endpoint(req: AutoProbeRequest):
    """Automatically probes any API URL, cURL, or raw API key (Google Gemini, OpenAI, Claude, Stripe, GitHub)."""
    target = resolve_api_input(req.url, method_override=req.method, auth_token_override=req.auth_token)

    start_time = time.perf_counter()
    status_code = 0
    elapsed_ms = 0.0
    extracted_schema = None
    resp_headers = {}

    try:
        probe_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        }
        if target.headers:
            probe_headers.update(target.headers)

        async with httpx.AsyncClient(timeout=12.0, headers=probe_headers, follow_redirects=True) as client:
            req_kwargs = {
                "method": target.method.value,
                "url": target.url,
            }
            if target.payload:
                req_kwargs["json"] = target.payload

            resp = await client.request(**req_kwargs)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            status_code = resp.status_code
            resp_headers = dict(resp.headers)

            try:
                body = resp.json()
                extracted_schema = extract_schema(body)
            except Exception:
                extracted_schema = None
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        status_code = 502

    # Auto-discover rate limits and changelog
    auto_lim, auto_rem, auto_res = auto_discover_rate_limit_headers(resp_headers)
    changelog_doc = await auto_probe_changelog_url(target.base_url, resp_headers)

    return {
        "name": target.inferred_name,
        "base_url": target.base_url,
        "endpoint_path": target.endpoint_path,
        "method": target.method,
        "status_code": status_code,
        "response_time_ms": elapsed_ms,
        "response_schema": extracted_schema,
        "rate_limit_header_limit": auto_lim,
        "rate_limit_header_remaining": auto_rem,
        "rate_limit_header_reset": auto_res,
        "changelog_url": changelog_doc,
        "is_sandbox": target.is_sandbox or (target.method != HttpMethod.GET),
        "detected_provider": target.detected_provider,
        "resolved_url": target.url,
        "test_payload": target.payload,
        "custom_headers": target.headers,
        "recommended_interval": 15 if "ratelimit" in str(resp_headers).lower() else 30
    }


@router.post("/auto-track", response_model=TrackedAPIResponse, status_code=status.HTTP_201_CREATED)
async def auto_track_endpoint(
    req: AutoTrackRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Completely automated onboarding: probes URL/API Key, learns contract & rate limits, and starts monitoring!"""
    probe_res = await auto_probe_endpoint(AutoProbeRequest(url=req.url, method=req.method, auth_token=req.auth_token))
    
    # Enforce sandbox guardrail on mutating calls
    is_sandbox = req.is_sandbox or probe_res.get("is_sandbox", False)
    if req.method in (HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE):
        is_sandbox = True  # Auto-confirmed for auto-track

    auth_token = req.auth_token or probe_res.get("auth_token")
    auth_type = AuthType.BEARER if auth_token else AuthType.NONE
    encrypted_auth = encrypt_secret({"token": auth_token}) if auth_token else None

    api = TrackedAPI(
        session_id=req.session_id,
        name=req.name or probe_res["name"],
        base_url=probe_res["base_url"],
        endpoint_path=probe_res["endpoint_path"],
        method=probe_res["method"],
        is_sandbox=is_sandbox,
        test_payload=probe_res.get("test_payload"),
        custom_headers=probe_res.get("custom_headers"),
        auth_type=auth_type,
        auth_config=encrypted_auth,
        check_interval_minutes=req.check_interval_minutes or probe_res.get("recommended_interval", 30),
        status=ApiStatus.ACTIVE,
        rate_limit_header_limit=probe_res.get("rate_limit_header_limit"),
        rate_limit_header_remaining=probe_res.get("rate_limit_header_remaining"),
        rate_limit_header_reset=probe_res.get("rate_limit_header_reset"),
        changelog_url=probe_res.get("changelog_url")
    )
    db.add(api)
    await db.commit()
    await db.refresh(api)

    schedule_api_job(api.id, api.check_interval_minutes)
    background_tasks.add_task(run_full_check, api.id)

    return api


@router.post("", response_model=TrackedAPIResponse, status_code=status.HTTP_201_CREATED)
async def create_tracked_api(
    payload: TrackedAPICreate,
    background_tasks: BackgroundTasks,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    db: AsyncSession = Depends(get_db)
):
    """Adds a new API to monitor.
    
    Mutating methods (POST/PUT/PATCH/DELETE) require is_sandbox=True.
    Auth credentials are encrypted at rest using Fernet.
    Automatically executes the initial check in the background.
    """
    # Encrypt auth config if provided
    encrypted_auth = None
    if payload.auth_config:
        encrypted_auth = encrypt_secret(payload.auth_config)

    api = TrackedAPI(
        session_id=payload.session_id or x_session_id,
        name=payload.name,
        base_url=payload.base_url,
        endpoint_path=payload.endpoint_path,
        method=payload.method,
        is_sandbox=payload.is_sandbox,
        test_payload=payload.test_payload,
        custom_headers=payload.custom_headers,
        auth_type=payload.auth_type,
        auth_config=encrypted_auth,
        check_interval_minutes=payload.check_interval_minutes,
        status=payload.status,
        rate_limit_header_limit=payload.rate_limit_header_limit,
        rate_limit_header_remaining=payload.rate_limit_header_remaining,
        rate_limit_header_reset=payload.rate_limit_header_reset,
        changelog_url=payload.changelog_url
    )
    db.add(api)
    await db.commit()
    await db.refresh(api)

    # Schedule monitoring check if active
    if api.status == ApiStatus.ACTIVE:
        schedule_api_job(api.id, api.check_interval_minutes)
        # Automatically fire initial check in background!
        background_tasks.add_task(run_full_check, api.id)

    return api


@router.get("", response_model=List[TrackedAPIResponse])
async def list_tracked_apis(
    status_filter: Optional[ApiStatus] = Query(None, alias="status"),
    session_id: Optional[str] = Query(None, alias="session_id"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """Lists all tracked APIs with live operational status, latency, and creation/modification timestamps."""
    active_session = session_id or x_session_id
    query = select(TrackedAPI)
    
    if active_session:
        # User sees only their own session's APIs
        query = query.where(TrackedAPI.session_id == active_session)
    if status_filter:
        query = query.where(TrackedAPI.status == status_filter)
    query = query.order_by(TrackedAPI.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    apis = list(result.scalars().all())

    responses = []
    for api in apis:
        snap_stmt = (
            select(ApiSnapshot)
            .where(ApiSnapshot.tracked_api_id == api.id)
            .order_by(ApiSnapshot.checked_at.desc())
            .limit(1)
        )
        snap_res = await db.execute(snap_stmt)
        latest_snap = snap_res.scalars().first()

        item = TrackedAPIResponse.model_validate(api)
        if latest_snap:
            item.last_status_code = latest_snap.status_code
            item.last_response_time_ms = latest_snap.response_time_ms
            item.last_checked_at = latest_snap.checked_at
            item.is_working = (200 <= latest_snap.status_code < 400)
        responses.append(item)

    return responses


@router.get("/{api_id}", response_model=TrackedAPIResponse)
async def get_tracked_api(
    api_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Retrieves metadata and current live operational status for a specific tracked API."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    snap_stmt = (
        select(ApiSnapshot)
        .where(ApiSnapshot.tracked_api_id == api.id)
        .order_by(ApiSnapshot.checked_at.desc())
        .limit(1)
    )
    snap_res = await db.execute(snap_stmt)
    latest_snap = snap_res.scalars().first()

    item = TrackedAPIResponse.model_validate(api)
    if latest_snap:
        item.last_status_code = latest_snap.status_code
        item.last_response_time_ms = latest_snap.response_time_ms
        item.last_checked_at = latest_snap.checked_at
        item.is_working = (200 <= latest_snap.status_code < 400)
    return item


@router.patch("/{api_id}", response_model=TrackedAPIResponse)
async def update_tracked_api(
    api_id: int,
    payload: TrackedAPIUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Updates configuration for a tracked API."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Re-validate sandbox guardrail if method or is_sandbox is updated
    new_method = update_data.get("method", api.method)
    new_is_sandbox = update_data.get("is_sandbox", api.is_sandbox)
    mutating = {HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE}
    if new_method in mutating and not new_is_sandbox:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mutating HTTP methods require is_sandbox=True."
        )

    # Re-encrypt auth_config if updated
    if "auth_config" in update_data:
        raw_auth = update_data.pop("auth_config")
        api.auth_config = encrypt_secret(raw_auth) if raw_auth else None

    for field, value in update_data.items():
        setattr(api, field, value)

    await db.commit()
    await db.refresh(api)

    # Adjust scheduler jobs according to new status / interval
    if api.status == ApiStatus.ACTIVE:
        schedule_api_job(api.id, api.check_interval_minutes)
    else:
        remove_api_job(api.id)

    return api


@router.delete("/{api_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tracked_api(
    api_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Deletes a tracked API and unregisters its scheduled jobs."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    remove_api_job(api.id)
    await db.delete(api)
    await db.commit()
    return None


@router.post("/{api_id}/check", response_model=Optional[ApiSnapshotResponse])
async def trigger_manual_check(
    api_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Triggers an immediate on-demand monitoring check for a tracked API."""
    api = await db.get(TrackedAPI, api_id)
    if not api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API {api_id} not found")

    snapshot = await run_full_check(api_id, db=db, force=True)
    return snapshot
