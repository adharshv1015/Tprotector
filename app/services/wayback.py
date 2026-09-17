import json
import logging
from datetime import datetime
from typing import Any, List, Optional
import httpx

from app.models.schema_diff import DiffSeverity
from app.schemas.snapshot import DeepHistoryResponse, SchemaDiffResponse
from app.services.schema_diff import extract_schema, diff_schemas

logger = logging.getLogger(__name__)

async def fetch_wayback_history(url: str, base_url: str, tracked_api_id: int) -> Optional[DeepHistoryResponse]:
    """Fetches historical schema diffs for a given URL using the Internet Archive CDX API."""
    cdx_url = f"https://web.archive.org/cdx/search/cdx?url={url}&output=json&fl=timestamp,statuscode,digest,original&filter=statuscode:200&collapse=digest&limit=15"
    
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
            
            # Process snapshots chronologically
            for row in snapshots:
                timestamp = row[0]
                original_url = row[3]
                
                # Fetch raw content from Wayback Machine
                # The id_ suffix ensures we get the raw response without Wayback toolbar injection
                snapshot_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
                
                try:
                    snap_res = await client.get(snapshot_url, timeout=10.0)
                    if snap_res.status_code == 200:
                        try:
                            json_content = snap_res.json()
                            current_schema = extract_schema(json_content)
                            
                            if previous_schema is not None:
                                severity, diff_summary = diff_schemas(previous_schema, current_schema)
                                if severity != DiffSeverity.INFORMATIONAL or "initial_snapshot" not in diff_summary:
                                    dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
                                    diffs.append(SchemaDiffResponse(
                                        id=0,
                                        tracked_api_id=tracked_api_id,
                                        old_schema=previous_schema,
                                        new_schema=current_schema,
                                        diff_summary=diff_summary,
                                        severity=severity,
                                        detected_at=dt
                                    ))
                                
                            previous_schema = current_schema
                        except json.JSONDecodeError:
                            # Skip non-JSON snapshots
                            continue
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
