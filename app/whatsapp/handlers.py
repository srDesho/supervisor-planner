"""
WhatsApp message event dispatcher and idempotency gatekeeper.
Ensures identical message events from WAHA are executed at most once.
"""
import logging

from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp import idempotency
from app.services.planning_service import PlanningService

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

    planning_svc = PlanningService()
    await planning_svc.handle_message(message)
    return True
