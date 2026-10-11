"""
In-memory idempotency guard for inbound WhatsApp messages.

Mirrors the accepted MVP limitation of app/services/conversation_service.py:
state lives only in process memory and is lost on restart. This guards
against WAHA webhook retries, which happen within seconds of the original
delivery, so the trade-off is acceptable for the MVP.
"""
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

_MAX_TRACKED_MESSAGES = 10_000
_processed: "OrderedDict[str, None]" = OrderedDict()


def is_processed(message_id: str) -> bool:
    return message_id in _processed


def mark_processed(message_id: str) -> None:
    if message_id in _processed:
        return
    _processed[message_id] = None
    if len(_processed) > _MAX_TRACKED_MESSAGES:
        _processed.popitem(last=False)


def clear() -> None:
    """Testing helper: clears all tracked message ids."""
    _processed.clear()
