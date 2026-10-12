"""
WhatsApp message event dispatcher.

For every inbound message, in this order:
1. Idempotency check (already-processed message ids are dropped, before any lock).
2. Resolve the sender's phone (cached) -> it keys the lock and the duplicate check.
3. Duplicate suppression: the same text from the same phone within a couple of
   seconds is a double-send (WhatsApp client glitch / double tap) and is ignored.
4. FIFO lock per phone (app/core/locks.py): one message per supervisor at a time.
5. Process; only AFTER it succeeded is the message id marked as processed, so a
   WAHA retry of a message that failed is not discarded.
6. If processing raised, the (authenticated) supervisor gets a fallback reply.
"""
import logging
import time
from typing import Dict, Optional, Tuple

from app.config import get_settings
from app.core.locks import phone_lock, touch_activity
from app.core.singletons import get_planning_service
from app.sheets.client import run_in_sheets_thread
from app.whatsapp import idempotency
from app.whatsapp.lid_resolver import resolve_to_phone
from app.whatsapp.parser import ParsedWhatsAppMessage, normalize_command
from app.whatsapp.templates import MSG_PROCESSING_ERROR

logger = logging.getLogger(__name__)

# Monotonic clock, module-level so tests can drive it.
_now = time.monotonic

# phone -> (normalized text, time of the last message with that phone).
_last_message: Dict[str, Tuple[str, float]] = {}
_LAST_MESSAGE_PRUNE_THRESHOLD = 1000


def _is_duplicate(phone: str, normalized_text: str) -> bool:
    """
    True if `phone` sent the same normalized text less than
    DUPLICATE_MESSAGE_WINDOW_SECONDS ago. The timestamp is refreshed on every
    message, so a burst of identical messages keeps being suppressed.
    """
    window = get_settings().DUPLICATE_MESSAGE_WINDOW_SECONDS
    now = _now()
    previous = _last_message.get(phone)
    _last_message[phone] = (normalized_text, now)

    if len(_last_message) > _LAST_MESSAGE_PRUNE_THRESHOLD:
        for key in [k for k, (_, ts) in _last_message.items() if now - ts > window]:
            del _last_message[key]

    return previous is not None and previous[0] == normalized_text and now - previous[1] < window


def reset_duplicate_tracking() -> None:
    """Testing helper."""
    _last_message.clear()


async def _send_failure_reply(phone: Optional[str], chat_id: str) -> None:
    """
    Tells the supervisor something went wrong. Only authenticated supervisors
    get it: unknown senders keep the total-silence rule even when we fail.
    Never raises (it runs inside an error path).
    """
    try:
        planning_svc = get_planning_service()
        supervisor = None
        if phone:
            supervisor = await run_in_sheets_thread(planning_svc.supervisor_svc.authenticate, phone)
        if supervisor:
            await planning_svc.whatsapp_client.send_message(chat_id, MSG_PROCESSING_ERROR)
    except Exception:
        logger.error("Could not send the fallback reply to %s", phone or chat_id, exc_info=True)


async def handle_whatsapp_event(message: ParsedWhatsAppMessage) -> bool:
    """
    Processes a parsed incoming WhatsApp message.
    Returns True if it was processed successfully, False if it was ignored
    (duplicate id, duplicate text) or failed.
    """
    message_id = message.message_id
    if idempotency.is_processed(message_id):
        logger.warning(
            f"Duplicate WhatsApp message received and ignored: ID={message_id} from {message.from_phone}"
        )
        return False

    chat_id = message.from_full or message.from_phone
    phone = await resolve_to_phone(chat_id)
    # Unresolvable senders get no reply anyway; key them by chat id so their
    # messages still serialize among themselves.
    key = phone or chat_id

    if phone and _is_duplicate(phone, normalize_command(message.body)):
        logger.info(f"Suppressed duplicate message from {phone} id={message_id}")
        idempotency.mark_processed(message_id)
        return False

    async with phone_lock(key):
        # A WAHA retry of a message we were still processing (or waiting for the
        # lock) arrives here after the first attempt finished: check again.
        if idempotency.is_processed(message_id):
            logger.warning(f"Duplicate WhatsApp message ignored after waiting: ID={message_id} from {key}")
            return False

        started = time.monotonic()
        logger.info(f"Processing message from {key} id={message_id}")
        if phone:
            touch_activity(phone)

        try:
            await get_planning_service().handle_message(message)
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.error(
                f"Failed message from {key} id={message_id} in {elapsed:.1f}s: {exc}", exc_info=True
            )
            # Not marked as processed (a retry may succeed), and the supervisor may
            # legitimately resend the same text right away.
            if phone:
                _last_message.pop(phone, None)
            await _send_failure_reply(phone, chat_id)
            return False

        idempotency.mark_processed(message_id)
        logger.info(f"Finished message from {key} id={message_id} in {time.monotonic() - started:.1f}s")
        return True
