import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tracked_api import ApiStatus, TrackedAPI
from app.scheduler.runner import run_full_check
from app.services.latency import recalculate_baseline_for_api

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def get_job_id(api_id: int) -> str:
    return f"check_api_{api_id}"


def schedule_api_job(api_id: int, interval_minutes: int) -> None:
    """Adds or updates an interval job for an API."""
    job_id = get_job_id(api_id)
    # Remove existing job if present
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        run_full_check,
        trigger=IntervalTrigger(minutes=max(1, interval_minutes)),
        id=job_id,
        args=[api_id],
        replace_existing=True,
        name=f"Monitoring check for API {api_id}"
    )
    logger.info(f"Scheduled check job for API {api_id} every {interval_minutes} minutes.")


def remove_api_job(api_id: int) -> None:
    """Removes the scheduled job for an API if it exists."""
    job_id = get_job_id(api_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Removed check job for API {api_id}.")


async def recalculate_all_baselines() -> None:
    """Nightly task recalculating rolling latency baselines for all active APIs."""
    logger.info("Executing nightly latency baseline recalculation.")
    async with AsyncSessionLocal() as db:
        query = select(TrackedAPI.id).where(TrackedAPI.status == ApiStatus.ACTIVE)
        result = await db.execute(query)
        api_ids = result.scalars().all()

        for api_id in api_ids:
            try:
                await recalculate_baseline_for_api(db, api_id, days=7)
            except Exception as e:
                logger.error(f"Failed to recalculate baseline for API {api_id}: {e}")


async def sync_jobs_from_db() -> None:
    """Idempotently registers monitoring jobs for all active APIs found in the database on startup."""
    logger.info("Synchronizing scheduled API jobs from database.")
    async with AsyncSessionLocal() as db:
        query = select(TrackedAPI).where(TrackedAPI.status == ApiStatus.ACTIVE)
        result = await db.execute(query)
        active_apis = result.scalars().all()

        for api in active_apis:
            schedule_api_job(api.id, api.check_interval_minutes)

    # Register daily midnight baseline recalculation
    scheduler.add_job(
        recalculate_all_baselines,
        trigger=CronTrigger(hour=0, minute=0),
        id="nightly_baseline_recalculation",
        replace_existing=True,
        name="Nightly 7-day latency baseline recalculation"
    )


def start_scheduler() -> None:
    """Starts the APScheduler instance."""
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started.")


def stop_scheduler() -> None:
    """Shuts down the APScheduler instance."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
