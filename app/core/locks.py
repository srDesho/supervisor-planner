"""
Per-phone coordination shared by the message handler and the reminder cycle.

phone_lock(phone): a FIFO asyncio lock per supervisor.
  Why it exists: every handler yields to the event loop (HTTP to WAHA, the
  Sheets thread), so two messages from the same supervisor sent in quick
  succession used to be processed interleaved and stepped on each other's
  conversation state (replies out of order, double registrations, a reminder
  slipping between the question and the answer). With the lock each message is
  processed completely (reply included) before the next one of the SAME phone
  starts. Different supervisors never wait for each other. asyncio.Lock wakes
  waiters in arrival order, so messages are served FIFO.
  The reminder cycle takes the same lock before writing to a supervisor.

  Why the cleanup: the dict is keyed by phone and would otherwise keep one
  lock per phone number that ever wrote to the bot, forever (including
  unknown senders). Each entry counts the coroutines using it (holding or
  waiting) and is deleted when the count drops to zero. The count is our own
  because asyncio.Lock exposes no public "waiters" API (its _waiters is
  private and may be None).

  Everything here is single-threaded asyncio state (one uvicorn worker): there
  is no await between looking an entry up and counting it, so it needs no
  extra locking.

touch_activity / seconds_since_activity: in-memory "last time this phone wrote
  to the bot", used by reminders to avoid interrupting a live conversation.
  Lost on restart, like the conversation state itself.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional

# Monotonic clock, module-level so tests can drive it.
_now = time.monotonic


class _Entry:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.users = 0  # coroutines currently holding or waiting for the lock


_locks: Dict[str, _Entry] = {}
_last_activity: Dict[str, float] = {}

# Entries older than this are dropped when the activity dict gets big.
_ACTIVITY_PRUNE_AFTER_SECONDS = 6 * 60 * 60
_ACTIVITY_PRUNE_THRESHOLD = 1000


@asynccontextmanager
async def phone_lock(phone: str) -> AsyncIterator[None]:
    entry = _locks.get(phone)
    if entry is None:
        entry = _locks[phone] = _Entry()
    entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        entry.users -= 1
        if entry.users == 0:
            _locks.pop(phone, None)


def active_lock_count() -> int:
    """How many phones currently hold or wait for a lock (for tests/diagnostics)."""
    return len(_locks)


def touch_activity(phone: str) -> None:
    """Records that `phone` just wrote to the bot."""
    now = _now()
    _last_activity[phone] = now
    if len(_last_activity) > _ACTIVITY_PRUNE_THRESHOLD:
        cutoff = now - _ACTIVITY_PRUNE_AFTER_SECONDS
        for key in [k for k, ts in _last_activity.items() if ts < cutoff]:
            del _last_activity[key]


def seconds_since_activity(phone: str) -> Optional[float]:
    """Seconds since `phone` last wrote to the bot, or None if unknown (e.g. after a restart)."""
    ts = _last_activity.get(phone)
    return None if ts is None else _now() - ts


def reset() -> None:
    """Testing helper."""
    _locks.clear()
    _last_activity.clear()
