"""
WhatsApp message event dispatcher and idempotency gatekeeper.
Ensures identical message events from WAHA are executed at most once.
"""
import logging

from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp import idempotency
from app.core.singletons import get_planning_service

logger = logging.getLogger(__name__)


async def handle_whatsapp_event(message: ParsedWhatsAppMessage) -> bool:
    """
    Processes a parsed incoming WhatsApp message.
    1. Checks idempotency: if message_id was already processed, ignores it.
    2. Marks message_id as processed.
    3. Hands off to PlanningService.
    Returns True if processed, False if duplicate.
    """
    if idempotency.is_processed(message.message_id):
        logger.warning(
            f"Duplicate WhatsApp message received and ignored: ID={message.message_id} from {message.from_phone}"
        )
        return False

    idempotency.mark_processed(message.message_id)

    # Shared instance: it keeps no per-message state, and building a new one per
    # message would rebuild the Sheets clients and caches (see app/core/singletons.py).
    planning_svc = get_planning_service()
    await planning_svc.handle_message(message)
    return True
