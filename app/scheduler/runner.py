import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.deprecation import DeprecationNotice
from app.models.event import EventSeverity
from app.models.rate_limit import RateLimitTracking
from app.models.schema_diff import DiffSeverity, SchemaDiff
from app.models.snapshot import ApiSnapshot
from app.models.tracked_api import ApiStatus, TrackedAPI
from app.services.deprecation import auto_probe_changelog_url, inspect_changelog
from app.services.events import record_event
from app.services.http_client import execute_monitored_request
from app.services.latency import check_drift, get_latest_baseline, recalculate_baseline_for_api
from app.services.rate_limit import auto_discover_rate_limit_headers, extract_rate_limit
from app.services.schema_diff import diff_schemas, extract_schema

logger = logging.getLogger(__name__)


async def run_full_check(api_id: int, db: Optional[AsyncSession] = None, force: bool = False) -> Optional[ApiSnapshot]:
    """Executes a full monitoring check for a single tracked API.
    
    Guarantees:
    - Retries happen internally in http_client. Exactly one snapshot row is created per check.
    - Schema diffing always compares against the most recent successful snapshot with a valid schema.
    """
    if db is not None:
        return await _execute_check(api_id, db, force=force)

    async with AsyncSessionLocal() as session:
        return await _execute_check(api_id, session, force=force)


async def _execute_check(api_id: int, db: AsyncSession, force: bool = False) -> Optional[ApiSnapshot]:
    query = select(TrackedAPI).where(TrackedAPI.id == api_id)
    result = await db.execute(query)
    tracked_api = result.scalars().first()

    if not tracked_api:
        logger.info(f"API {api_id} not found. Skipping check.")
        return None

    if tracked_api.status == ApiStatus.PAUSED and not force:
        logger.info(f"API {api_id} is paused and force check not requested. Skipping check.")
        return None

    # Sanitize legacy bot User-Agent if stored from initial scanner
    if tracked_api.custom_headers and any(b in str(v).lower() for v in tracked_api.custom_headers.values() for b in ["tprotector-observer", "aegis-observer", "apimonitor-agent"]):
        tracked_api.custom_headers = {
            k: v for k, v in tracked_api.custom_headers.items()
            if not (k.lower() == "user-agent" and any(b in str(v).lower() for b in ["tprotector-observer", "aegis-observer", "apimonitor-agent", "python-httpx"]))
        }
        await db.commit()

    # 1. Execute HTTP request (with retry & backoff handled inside)
    response, elapsed_ms, error = await execute_monitored_request(tracked_api)

    status_code = response.status_code if response is not None else 0
    headers_dict = dict(response.headers) if response is not None else {}
    extracted_schema = None

    if response is not None:
        content_type = response.headers.get("content-type", "").lower()
        try:
            if "json" in content_type:
                # JSON response — extract full structural schema
                data = response.json()
                extracted_schema = extract_schema(data)
            elif "xml" in content_type or response.text.strip().startswith("<"):
                # XML response — parse tags into a structural summary
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(response.text.strip())
                    def xml_to_schema(el, depth=0):
                        children = list(el)
                        if not children or depth > 4:
                            return "str" if el.text and el.text.strip() else "empty"
                        return {child.tag.split("}")[-1]: xml_to_schema(child, depth + 1) for child in children[:10]}
                    extracted_schema = {"_format": "xml", "_root": root.tag.split("}")[-1], "_structure": xml_to_schema(root)}
                except ET.ParseError:
                    extracted_schema = {"_format": "xml", "_parse_error": "str"}
            else:
                # Plain text — summarise structure (e.g. robots.txt, CSV)
                lines = [l.strip() for l in response.text.strip().splitlines() if l.strip()]
                unique_prefixes = list(dict.fromkeys(l.split(":")[0].strip() for l in lines if ":" in l))
                extracted_schema = {
                    "_format": "text",
                    "_line_count": "int",
                    "_directives": [p for p in unique_prefixes[:10]] if unique_prefixes else []
                }
        except Exception:
            extracted_schema = None

    # 2. Invariant: Exactly one ApiSnapshot row persisted
    snapshot = ApiSnapshot(
        tracked_api_id=api_id,
        response_schema=extracted_schema,
        status_code=status_code,
        response_time_ms=elapsed_ms,
        headers_snapshot=headers_dict,
        checked_at=datetime.now(timezone.utc)
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    # 3. Handle network / connection failures
    if error:
        await record_event(
            db=db,
            tracked_api_id=api_id,
            event_type="connection_error",
            severity=EventSeverity.HIGH,
            message=f"Check failed for {tracked_api.name}: {error}"
        )
        return snapshot
        
    # 3.5. Handle HTTP Errors (4xx, 5xx)
    if status_code >= 400:
        await record_event(
            db=db,
            tracked_api_id=api_id,
            event_type="http_error",
            severity=EventSeverity.HIGH,
            message=f"API returned HTTP Error: {status_code} for {tracked_api.name}"
        )
        # We don't return early here so we can still track schema changes even on error pages

    # 4. Schema Diffing (Compares strictly against latest successful schema snapshot)
    if extracted_schema is not None:
        # Query last snapshot prior to current one that contains a valid schema with 2xx status
        last_snapshot_query = (
            select(ApiSnapshot)
            .where(
                ApiSnapshot.tracked_api_id == api_id,
                ApiSnapshot.id != snapshot.id,
                ApiSnapshot.response_schema.is_not(None),
                ApiSnapshot.status_code >= 200,
                ApiSnapshot.status_code < 300
            )
            .order_by(ApiSnapshot.checked_at.desc())
            .limit(1)
        )
        last_snap_res = await db.execute(last_snapshot_query)
        last_snapshot = last_snap_res.scalars().first()
        old_schema = last_snapshot.response_schema if last_snapshot else None

        severity, diff_summary = diff_schemas(old_schema, extracted_schema)

        # Record diff if there is an old schema and changes were detected
        if old_schema is not None and diff_summary:
            diff_record = SchemaDiff(
                tracked_api_id=api_id,
                old_schema=old_schema,
                new_schema=extracted_schema,
                diff_summary=diff_summary,
                severity=severity,
                detected_at=datetime.now(timezone.utc)
            )
            db.add(diff_record)
            await db.commit()

            # Map to event severity
            event_severity = (
                EventSeverity.BREAKING if severity == DiffSeverity.BREAKING
                else (EventSeverity.LOW if severity == DiffSeverity.NON_BREAKING else EventSeverity.INFO)
            )
            
            await record_event(
                db=db,
                tracked_api_id=api_id,
                event_type="schema_change",
                severity=event_severity,
                message=f"Major Rule Change (The plug shape changed): Old ways will fail for {tracked_api.name} [{tracked_api.endpoint_path}]",
                old_value=old_schema,
                new_value=extracted_schema
            )

    # 5. Rate Limit Header Tracking & Automated Discovery
    if not tracked_api.rate_limit_header_limit:
        auto_lim, auto_rem, auto_res = auto_discover_rate_limit_headers(headers_dict)
        if auto_lim and auto_rem:
            tracked_api.rate_limit_header_limit = auto_lim
            tracked_api.rate_limit_header_remaining = auto_rem
            tracked_api.rate_limit_header_reset = auto_res
            await db.commit()

    limit_val, remaining_val, reset_val, usage_pct, is_warning = extract_rate_limit(
        headers=headers_dict,
        tracked_api=tracked_api
    )
    if usage_pct is not None:
        rl_record = RateLimitTracking(
            tracked_api_id=api_id,
            limit_header_value=limit_val,
            remaining_header_value=remaining_val,
            reset_header_value=reset_val,
            usage_percent=usage_pct,
            checked_at=datetime.now(timezone.utc)
        )
        db.add(rl_record)
        await db.commit()

        if is_warning:
            await record_event(
                db=db,
                tracked_api_id=api_id,
                event_type="rate_limit_warning",
                severity=EventSeverity.MEDIUM,
                message=f"Rate limit usage warning: {usage_pct}% consumed ({remaining_val}/{limit_val} remaining) for {tracked_api.name}"
            )

    # 6. Latency & Anomaly Drift Detection (Auto-initializes baseline after 3 checks)
    baseline = await get_latest_baseline(db, api_id)
    if not baseline:
        # Check snapshot count to auto-generate baseline early
        count_q = select(ApiSnapshot.id).where(ApiSnapshot.tracked_api_id == api_id)
        count_res = await db.execute(count_q)
        if len(count_res.scalars().all()) >= 3:
            baseline = await recalculate_baseline_for_api(db, api_id, days=7)

    if baseline:
        is_spike, z_score = check_drift(elapsed_ms, baseline)
        if is_spike:
            await record_event(
                db=db,
                tracked_api_id=api_id,
                event_type="latency_spike",
                severity=EventSeverity.MEDIUM,
                message=f"Slowdown Alert: Things are moving much slower than normal for {tracked_api.name}: {elapsed_ms}ms (z-score: {z_score}, baseline avg: {baseline.avg_response_time_ms}ms)"
            )

    # 7. Deprecation & Documentation Scraping (Auto-probes URL once if not configured)
    if tracked_api.changelog_url is None:
        discovered_doc = await auto_probe_changelog_url(tracked_api.base_url, headers_dict)
        tracked_api.changelog_url = discovered_doc or ""
        await db.commit()

    if tracked_api.changelog_url:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                c_resp = await client.get(tracked_api.changelog_url, follow_redirects=True)
                if c_resp.status_code == 200:
                    has_changed, new_hash, matches = inspect_changelog(tracked_api, c_resp.text)
                    if has_changed:
                        tracked_api.last_changelog_hash = new_hash
                        await db.commit()

                        for mention in matches:
                            notice = DeprecationNotice(
                                tracked_api_id=api_id,
                                source_url=tracked_api.changelog_url,
                                notice_text=mention,
                                detected_at=datetime.now(timezone.utc)
                            )
                            db.add(notice)
                        await db.commit()

                        msg = f"Writing in a Diary: Someone made a change, and we wrote it down for {tracked_api.name}."
                        if matches:
                            msg += f" Flagged {len(matches)} potential deprecation mention(s)."
                        
                        await record_event(
                            db=db,
                            tracked_api_id=api_id,
                            event_type="changelog_updated",
                            severity=EventSeverity.MEDIUM if matches else EventSeverity.INFO,
                            message=msg,
                            new_value={"matches": matches} if matches else None
                        )
        except Exception as e:
            logger.warning(f"Failed to scrape changelog for API {api_id}: {e}")

    return snapshot
