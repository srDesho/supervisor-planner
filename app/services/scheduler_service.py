"""
APScheduler background service configuration.

Uses a CronTrigger aligned to the wall-clock (minute 0 and 30 for a 30-minute
interval) rather than a plain interval trigger: the reminder policy expects
ticks to land on exact times (15:00, 15:30, ..., REMINDER_ESCALATION_TIME,
SATURDAY_NOTICE_TIME), which an unaligned IntervalTrigger can't guarantee.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.services.conversation_service import ConversationService
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _reminder_job_wrapper():
    """Sweeps expired conversation state, then triggers a reminder cycle."""
    logger.info("Executing scheduled reminder job...")
    ConversationService().clear_expired()
    reminder_svc = ReminderService()
    await reminder_svc.run_reminder_cycle()


def start_scheduler() -> None:
    """Configures and starts the background task scheduler."""
    settings = get_settings()
    interval_minutes = settings.REMINDER_INTERVAL_MINUTES

    scheduler.add_job(
        _reminder_job_wrapper,
        trigger=IntervalTrigger(minutes=interval_minutes, timezone=settings.TIMEZONE),
        id="reminder_cycle_job",
        name="Company Supervisor Reminder Cycle",
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"APScheduler started. Reminder cycle configured every {interval_minutes} minutes.")


def shutdown_scheduler() -> None:
    """Gracefully shuts down the background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler successfully shut down.")
