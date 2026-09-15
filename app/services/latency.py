import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.latency import LatencyBaseline
from app.models.snapshot import ApiSnapshot


def check_drift(
    current_latency_ms: float,
    baseline: Optional[LatencyBaseline],
    z_threshold: Optional[float] = None
) -> Tuple[bool, float]:
    """Calculates Z-score deviation against historical rolling baseline.
    
    Returns (is_anomaly, z_score).
    """
    if not baseline or baseline.std_dev_ms <= 0:
        return False, 0.0

    threshold = z_threshold if z_threshold is not None else settings.DEFAULT_LATENCY_ZSCORE_THRESHOLD
    z_score = (current_latency_ms - baseline.avg_response_time_ms) / baseline.std_dev_ms
    is_spike = z_score > threshold
    return is_spike, round(z_score, 2)


def compute_metrics(snapshots: List[ApiSnapshot]) -> Tuple[float, float, float]:
    """Computes mean response time, standard deviation, and error rate percentage."""
    if not snapshots:
        return 0.0, 0.0, 0.0

    latencies = [s.response_time_ms for s in snapshots]
    n = len(latencies)
    avg = sum(latencies) / n

    variance = sum((x - avg) ** 2 for x in latencies) / n if n > 1 else 0.0
    std_dev = math.sqrt(variance)

    error_count = sum(1 for s in snapshots if s.status_code >= 400 or s.status_code == 0)
    error_rate = (error_count / n) * 100.0

    return round(avg, 2), round(std_dev, 2), round(error_rate, 2)


async def recalculate_baseline_for_api(
    db: AsyncSession,
    tracked_api_id: int,
    days: int = 7
) -> Optional[LatencyBaseline]:
    """Recalculates and persists rolling baseline for a tracked API over the last N days."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    query = select(ApiSnapshot).where(
        ApiSnapshot.tracked_api_id == tracked_api_id,
        ApiSnapshot.checked_at >= window_start
    )
    result = await db.execute(query)
    snapshots = list(result.scalars().all())

    if not snapshots:
        return None

    avg, std_dev, error_rate = compute_metrics(snapshots)

    baseline = LatencyBaseline(
        tracked_api_id=tracked_api_id,
        avg_response_time_ms=avg,
        std_dev_ms=std_dev,
        error_rate_percent=error_rate,
        window_start=window_start,
        window_end=now
    )
    db.add(baseline)
    await db.commit()
    await db.refresh(baseline)
    return baseline


async def get_latest_baseline(
    db: AsyncSession,
    tracked_api_id: int
) -> Optional[LatencyBaseline]:
    """Fetches the most recent baseline entry for an API."""
    query = (
        select(LatencyBaseline)
        .where(LatencyBaseline.tracked_api_id == tracked_api_id)
        .order_by(LatencyBaseline.window_end.desc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalars().first()
