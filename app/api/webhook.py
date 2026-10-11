"""
WAHA incoming webhook receiver endpoint.
Extracts events, responds with 200 OK immediately and processes message events safely.
"""
import logging
from typing import Dict, Any
from fastapi import APIRouter, BackgroundTasks, Request

from app.whatsapp.parser import parse_waha_webhook
from app.whatsapp.handlers import handle_whatsapp_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Webhook"])


async def _process_webhook_in_background(payload: Dict[str, Any]):
    """Background execution to ensure WAHA webhook gets an immediate HTTP 200 response."""
    parsed = parse_waha_webhook(payload)
    if not parsed:
        logger.debug("Non-message or bot-self WAHA webhook ignored.")
        return

    try:
        await handle_whatsapp_event(parsed)
    except Exception as e:
        logger.error(f"Error processing background WhatsApp event: {e}", exc_info=True)


@router.post("/waha")
async def receive_waha_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Webhook endpoint configured in WAHA.
    Receives JSON payload, acknowledges with 200 OK, and triggers async processing.
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.warning(f"Malformed JSON in webhook request: {e}")
        return {"status": "error", "message": "Invalid JSON"}

    background_tasks.add_task(_process_webhook_in_background, payload)
    return {"status": "received"}
