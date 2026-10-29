"""
APScheduler wiring. Started/stopped by the FastAPI lifespan hook in main.py.

Deliberately AsyncIOScheduler (not BackgroundScheduler): the jobs are async
and touch the async SQLAlchemy session, so they must run on the same event
loop as the app rather than in a separate thread with its own loop.

`coalesce=True` and `max_instances=1` matter here: if the app was down over
several scheduled ticks, we want one catch-up run, not a burst of queued
duplicates — and never two copies of the same job running concurrently
against the same rows.

Known limitation, same class as the WebSocket ConnectionManager and the
Diary/Vault unlock store: this is an in-process scheduler. Run two Uvicorn
workers and both will fire every job. The jobs themselves are written to be
idempotent (see jobs_service), so the damage is bounded — but a real
horizontally-scaled deployment should either run the scheduler as a single
separate process/container, or move to Celery Beat with a shared broker.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.services import jobs_service

logger = logging.getLogger("artha.scheduler")
settings = get_settings()

scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler | None:
    global scheduler

    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled via SCHEDULER_ENABLED=false")
        return None

    if scheduler is not None and scheduler.running:
        return scheduler

    scheduler = AsyncIOScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}
    )

    # Daily at 00:15 — just after midnight so "due today" subscriptions are
    # logged on the day they're actually due, with a small buffer to avoid
    # racing anything else that keys off the date rollover.
    scheduler.add_job(
        jobs_service.job_convert_due_subscriptions,
        CronTrigger(hour=0, minute=15),
        id="convert_due_subscriptions",
        replace_existing=True,
    )

    # Daily at 09:00 — budget/goal alerts at a time a user might actually
    # look at their phone, rather than the middle of the night.
    scheduler.add_job(
        jobs_service.job_refresh_alerts,
        CronTrigger(hour=9, minute=0),
        id="refresh_alerts",
        replace_existing=True,
    )

    # Mondays at 09:05 — weekly digest, staggered five minutes after the
    # daily alert job so they don't contend for the same DB connections.
    scheduler.add_job(
        jobs_service.job_weekly_digest,
        CronTrigger(day_of_week="mon", hour=9, minute=5),
        id="weekly_digest",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with %s job(s)", len(scheduler.get_jobs()))
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    scheduler = None


def get_job_status() -> list[dict]:
    """Surfaced via an admin endpoint so 'are the jobs actually running?'
    is answerable without SSHing into the container and reading logs."""
    if scheduler is None or not scheduler.running:
        return []
    return [
        {
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
        for job in scheduler.get_jobs()
    ]
