"""
APScheduler background service configuration.

Uses a CronTrigger aligned to the wall-clock (e.g. minutes 0 and 30 for a
30-minute interval) rather than a plain IntervalTrigger: the reminder
schedule depends on exact times (08:00, 11:30, 12:00, 15:00, 18:00, ...),
which an IntervalTrigger -- relative to when the process started -- can't
guarantee.

Because the machine may boot a few minutes after a tick (e.g. 08:07), one
"startup check" cycle also runs right after the scheduler starts, unless the
next cron tick is imminent (see STARTUP_CHECK_SKIP_SECONDS).
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.business.dates import get_current_bolivia_datetime
from app.config import get_settings
from app.services.conversation_service import ConversationService
from app.core.singletons import get_reminder_service

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# A tick that was missed by more than this is dropped instead of run late.
MISFIRE_GRACE_SECONDS = 60

# If the next cron tick is this close (or closer), the startup check is
# skipped: the tick itself will run the cycle within seconds, and running
# both would send the same reminders twice.
STARTUP_CHECK_SKIP_SECONDS = 30


def build_cron_trigger(interval_minutes: int, timezone: str) -> CronTrigger:
    """
    Cron trigger on exact clock minutes: 60 -> :00 of every hour, 30 -> :00
    and :30, 1 -> every minute. The interval must divide 60 evenly,
    otherwise ticks would not repeat at the same minutes every hour.
    """
    if not 1 <= interval_minutes <= 60 or 60 % interval_minutes != 0:
        raise ValueError(
            f"REMINDER_INTERVAL_MINUTES={interval_minutes} must divide 60 evenly "
            "(1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30 or 60)."
        )
    minute = "0" if interval_minutes == 60 else f"*/{interval_minutes}"
    return CronTrigger(minute=minute, second=0, timezone=timezone)


def decide_startup_check(trigger: CronTrigger, now: datetime) -> Tuple[bool, float]:
    """
    Decides whether the startup check cycle should run now.
    Returns (should_run, seconds_until_next_tick). It runs only when the next
    cron tick is MORE than STARTUP_CHECK_SKIP_SECONDS away.
    """
    next_tick = trigger.get_next_fire_time(None, now)
    seconds = (next_tick - now).total_seconds()
    return seconds > STARTUP_CHECK_SKIP_SECONDS, seconds


async def _run_cycle(origin: str) -> None:
    """Sweeps expired conversation state, then runs one reminder cycle."""
    logger.info(f"{origin}: ejecutando ciclo de recordatorio.")
    ConversationService().clear_expired()
    # Shared instance (one Sheets client, warm caches): see app/core/singletons.py.
    reminder_svc = get_reminder_service()
    await reminder_svc.run_reminder_cycle()


async def _reminder_job_wrapper() -> None:
    """Regular cron tick."""
    await _run_cycle("Tick del scheduler")


async def _startup_check_job() -> None:
    """One-off cycle right after boot, to recover a tick missed while the machine was off."""
    await _run_cycle("Startup check")


def schedule_startup_check(trigger: CronTrigger, now: Optional[datetime] = None) -> bool:
    """
    Queues the one-off startup check cycle, unless the next cron tick is
    <= STARTUP_CHECK_SKIP_SECONDS away. Returns True if it was queued.

    The startup check runs the full normal cycle (day, window, cooldown...);
    nothing is bypassed. It happens once per process start, never per tick.
    """
    now = now or get_current_bolivia_datetime()
    should_run, seconds = decide_startup_check(trigger, now)
    if not should_run:
        logger.info(
            f"Startup check: omitido, próximo tick en {seconds:.0f} segundos "
            f"(<={STARTUP_CHECK_SKIP_SECONDS})."
        )
        return False

    logger.info(
        f"Startup check: ejecutando ciclo de recordatorio por arranque del bot "
        f"(próximo tick en {seconds:.0f} segundos)."
    )
    # No trigger -> APScheduler runs the job once, immediately.
    scheduler.add_job(
        _startup_check_job,
        id="startup_check_job",
        name="Startup reminder check",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
    return True


def start_scheduler() -> None:
    """Configures and starts the background task scheduler."""
    settings = get_settings()
    interval_minutes = settings.REMINDER_INTERVAL_MINUTES
    trigger = build_cron_trigger(interval_minutes, settings.TIMEZONE)

    scheduler.add_job(
        _reminder_job_wrapper,
        trigger=trigger,
        id="reminder_cycle_job",
        name="Company Supervisor Reminder Cycle",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        f"APScheduler started. Reminder cycle on clock-aligned ticks every {interval_minutes} minutes "
        f"(misfire grace {MISFIRE_GRACE_SECONDS}s)."
    )

    schedule_startup_check(trigger)


def shutdown_scheduler() -> None:
    """Gracefully shuts down the background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler successfully shut down.")
