from sqlalchemy.util import monkeypatch_proxied_specials
import json
import logging
from datetime import datetime
from typing import Any, List, Optional
import httpx

from app.models.schema_diff import DiffSeverity
from app.schemas.snapshot import DeepHistoryResponse, SchemaDiffResponse, TopologyArcheologyResponse, HistoricalEndpoint
from app.services.schema_diff import extract_schema, diff_schemas
from app.services.schema_diff import extract_schema, diff_schemas

logger = logging.getLogger(__name__)

# aadarsh monkeypatch_proxied_specials
TRACKED_HEADERS_ALLOWLIST = {
    "server",
    "via",
    "x-powered-by",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy"
}

def diff_headers(old_headers: dict, new_headers: dict) -> Optional[dict]:
    added = {}
    removed = {}
    changed = {}
    
    for k, v in new_headers.items():
        if k not in old_headers:
            added[k] = v
        elif old_headers[k] != v:
            changed[k] = {"old": old_headers[k], "new": v}
            
    for k, v in old_headers.items():
        if k not in new_headers:
            removed[k] = v
            
    if added or removed or changed:
        return {"added": added, "removed": removed, "changed": changed}
    return None

def detect_historical_leaks(removed_fields: list) -> list:
    """Heuristic to detect if a removed field was likely a sensitive data leak."""
    leaks = []
    sensitive_keywords = {"password", "token", "secret", "ssn", "key", "auth", "credential", "apikey", "session", "private"}
    for field in removed_fields:
        field_lower = str(field).lower()
        for kw in sensitive_keywords:
            if kw in field_lower:
                leaks.append(str(field))
                break
    return leaks

async def fetch_wayback_history(url: str, base_url: str, tracked_api_id: int) -> Optional[DeepHistoryResponse]:
    """Fetches historical schema diffs for a given URL using the Internet Archive CDX API."""
    cdx_url = f"https://web.archive.org/cdx/search/cdx?url={url}&output=json&fl=timestamp,statuscode,digest,original,mimetype&filter=statuscode:200&collapse=digest&limit=15"
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            cdx_res = await client.get(cdx_url)
            
            data = []
            if cdx_res.status_code == 200:
                data = cdx_res.json()
            
            if not data or len(data) <= 1:
                # Fallback to checking the base_url for first_seen_at
                fallback_url = f"https://web.archive.org/cdx/search/cdx?url={base_url}&output=json&fl=timestamp&limit=1"
                fallback_res = await client.get(fallback_url)
                if fallback_res.status_code == 200:
                    fb_data = fallback_res.json()
                    if fb_data and len(fb_data) > 1:
                        first_timestamp_str = fb_data[1][0]
                        first_seen_at = datetime.strptime(first_timestamp_str, "%Y%m%d%H%M%S")
                        return DeepHistoryResponse(first_seen_at=first_seen_at, diffs=[])
                return None
            
            # Skip header row
            snapshots = data[1:]
            
            if not snapshots:
                return None

            first_timestamp_str = snapshots[0][0]
            first_seen_at = datetime.strptime(first_timestamp_str, "%Y%m%d%H%M%S")
            
            diffs: List[SchemaDiffResponse] = []
            previous_schema = None
            previous_headers = None
            previous_mimetype = None
            
            # Process snapshots chronologically
            for row in snapshots:
                timestamp = row[0]
                original_url = row[3]
                mimetype = row[4] if len(row) > 4 else None
                
                # Fetch raw content from Wayback Machine
                # The id_ suffix ensures we get the raw response without Wayback toolbar injection
                snapshot_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
                
                try:
                    snap_res = await client.get(snapshot_url, timeout=10.0)
                    if snap_res.status_code == 200:
                        # Extract and filter headers
                        current_headers = {}
                        for k, v in snap_res.headers.items():
                            k_lower = k.lower()
                            if k_lower in TRACKED_HEADERS_ALLOWLIST:
                                current_headers[k_lower] = v

                        payload_bytes = len(snap_res.content) if snap_res.content else 0

                        current_schema = None
                        try:
                            json_content = snap_res.json()
                            current_schema = extract_schema(json_content)
                        except json.JSONDecodeError:
                            pass  # Not JSON, but we still track header changes!
                            
                        if previous_headers is not None:
                            severity = DiffSeverity.INFORMATIONAL
                            diff_summary = {}
                            has_schema_change = False
                            
                            if previous_schema is not None and current_schema is not None:
                                severity, diff_summary = diff_schemas(previous_schema, current_schema)
                                has_schema_change = severity != DiffSeverity.INFORMATIONAL or "initial_snapshot" not in diff_summary
                            elif current_schema is not None and previous_schema is None:
                                severity = DiffSeverity.LOW
                                diff_summary = {"content_type": "Response changed to JSON"}
                                has_schema_change = True
                            elif current_schema is None and previous_schema is not None:
                                severity = DiffSeverity.HIGH
                                diff_summary = {"content_type": "Response is no longer JSON"}
                                has_schema_change = True
                                
                            header_changes = diff_headers(previous_headers, current_headers)
                            has_header_change = header_changes is not None
                            
                            if has_schema_change or has_header_change:
                                if not has_schema_change:
                                    severity = DiffSeverity.LOW
                                    diff_summary = {"header_update": "Infrastructure headers changed"}

                                format_evolution = None
                                if previous_mimetype and mimetype and previous_mimetype != mimetype:
                                    # Typical CDX mimetypes: text/html, application/json, text/xml
                                    if previous_mimetype not in ["warc/revisit", "unk"] and mimetype not in ["warc/revisit", "unk"]:
                                        format_evolution = {"old": previous_mimetype, "new": mimetype}
                                        severity = DiffSeverity.CRITICAL

                                rate_limit_erosion = None
                                prev_limit_str = previous_headers.get("x-ratelimit-limit") or previous_headers.get("x-rate-limit-limit")
                                curr_limit_str = current_headers.get("x-ratelimit-limit") or current_headers.get("x-rate-limit-limit")
                                if prev_limit_str and curr_limit_str:
                                    try:
                                        prev_limit = int(prev_limit_str)
                                        curr_limit = int(curr_limit_str)
                                        if curr_limit < prev_limit:
                                            rate_limit_erosion = {"old": prev_limit, "new": curr_limit}
                                            severity = DiffSeverity.HIGH
                                    except ValueError:
                                        pass

                                historical_leaks = None
                                if has_schema_change and isinstance(diff_summary, dict):
                                    removed_fields = []
                                    if "dictionary_item_removed" in diff_summary:
                                        for k in diff_summary["dictionary_item_removed"]:
                                            clean_k = str(k).replace("root['", "").replace("']", "")
                                            removed_fields.append(clean_k)
                                    if "iterable_item_removed" in diff_summary:
                                        for k in diff_summary["iterable_item_removed"].keys():
                                            clean_k = str(k).replace("root['", "").replace("']", "")
                                            removed_fields.append(clean_k)
                                            
                                    if removed_fields:
                                        leaks = detect_historical_leaks(removed_fields)
                                        if leaks:
                                            historical_leaks = leaks
                                            severity = DiffSeverity.CRITICAL
                                    
                                dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
                                diffs.append(SchemaDiffResponse(
                                    id=0,
                                    tracked_api_id=tracked_api_id,
                                    old_schema=previous_schema,
                                    new_schema=current_schema,
                                    diff_summary=diff_summary,
                                    header_changes=header_changes,
                                    historical_leaks=historical_leaks,
                                    payload_bytes=payload_bytes,
                                    format_evolution=format_evolution,
                                    rate_limit_erosion=rate_limit_erosion,
                                    severity=severity,
                                    detected_at=dt
                                ))
                            
                        previous_schema = current_schema
                        previous_headers = current_headers
                        if mimetype and mimetype not in ["warc/revisit", "unk"]:
                            previous_mimetype = mimetype
                except httpx.RequestError as e:
                    logger.warning(f"Failed to fetch snapshot {snapshot_url}: {e}")
                    continue
            
            # Reverse diffs to be newest first, like our local diffs
            diffs.reverse()
            
            return DeepHistoryResponse(
                first_seen_at=first_seen_at,
                diffs=diffs
            )

    except Exception as e:
        logger.error(f"Error fetching wayback history for {url}: {e}")
        return None

async def discover_ghost_endpoints(base_url: str) -> Optional[TopologyArcheologyResponse]:
    """Queries the CDX API with a wildcard for application/json to discover historical and ghost endpoints."""
    clean_base = base_url.rstrip("/")
    # Query CDX for all JSON endpoints under this domain
    cdx_url = f"https://web.archive.org/cdx/search/cdx?url={clean_base}/*&output=json&fl=timestamp,original&filter=statuscode:200&filter=mimetype:application/json&collapse=urlkey&limit=500"
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(cdx_url)
            if res.status_code != 200:
                return None
            
            data = res.json()
            if not data or len(data) <= 1:
                return TopologyArcheologyResponse(ghost_endpoints=[], active_historical_endpoints=[])
                
            # Skip header row
            snapshots = data[1:]
            
            # Map of path -> most recent timestamp seen
            path_timestamps = {}
            from urllib.parse import urlparse
            
            for row in snapshots:
                timestamp_str = row[0]
                original_url = row[1]
                
                parsed = urlparse(original_url)
                path = parsed.path
                if parsed.query:
                    path += f"?{parsed.query}"
                    
                # We want the most recent timestamp per path
                dt = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")
                if path not in path_timestamps or dt > path_timestamps[path]:
                    path_timestamps[path] = dt
            
            if not path_timestamps:
                return TopologyArcheologyResponse(ghost_endpoints=[], active_historical_endpoints=[])
            
            # Construct full URLs to probe concurrently
            from app.services.endpoint_probe import probe_candidates_concurrently
            
            paths_to_probe = list(path_timestamps.keys())
            urls_to_probe = [f"{clean_base}{p}" for p in paths_to_probe]
            
            probe_results = await probe_candidates_concurrently(urls_to_probe, max_concurrency=10, timeout_seconds=8.0)
            probe_map = {res.url: res.status_code for res in probe_results}
            
            ghost_endpoints = []
            active_endpoints = []
            
            for url in urls_to_probe:
                parsed = urlparse(url)
                path = parsed.path
                if parsed.query:
                    path += f"?{parsed.query}"
                    
                status = probe_map.get(url, 404) # Default to 404 if probe failed/timeout
                
                endpoint = HistoricalEndpoint(
                    path=path,
                    last_seen_in_archive=path_timestamps[path],
                    current_status=status
                )
                
                if status in (404, 410, 500, 502, 503, 0):
                    ghost_endpoints.append(endpoint)
                else:
                    active_endpoints.append(endpoint)
            
            ghost_endpoints.sort(key=lambda e: e.last_seen_in_archive, reverse=True)
            active_endpoints.sort(key=lambda e: e.last_seen_in_archive, reverse=True)
            
            return TopologyArcheologyResponse(
                ghost_endpoints=ghost_endpoints,
                active_historical_endpoints=active_endpoints
            )
            
    except Exception as e:
        logger.error(f"Error discovering ghost endpoints for {base_url}: {e}")
        return None

