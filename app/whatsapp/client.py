"""
WhatsApp HTTP Client connecting to WAHA (WhatsApp HTTP API).
Handles asynchronous outbound messaging and provides a mock history buffer for testing.
"""
import logging
from typing import Optional, List, Dict, Any
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        session_name: Optional[str] = None
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.WAHA_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.WAHA_API_KEY
        self.session_name = session_name or settings.WAHA_SESSION
        # In-memory sent message log for testing and auditing
        self.sent_messages: List[Dict[str, Any]] = []

    async def send_message(self, recipient_phone: str, text: str) -> bool:
        """
        Sends a WhatsApp text message to a chatId via WAHA.

        `recipient_phone` should always be the full chatId as received from an
        inbound WAHA event (e.g. '{phone}@lid' under GOWS, or '{phone}@c.us' /
        '{id}@g.us' under other engines) — callers must pass it through
        unchanged rather than rebuild it. Reconstructing '{digits}@c.us' from a
        bare number only works for legacy engines and breaks GOWS/LID senders
        with "no LID found". The bare-number fallback below exists solely for
        proactive sends with no inbound chatId to reuse (reminders, admin
        alerts) and is not a substitute for the real chatId.

        NOTE: recipient_phone is coerced to str defensively because Google
        Sheets (gspread) returns numeric phone cells as int, not str.
        """
        # Defensive: gspread may return numeric cells as int/float.
        recipient_phone = str(recipient_phone)

        if "@" in recipient_phone:
            chat_id = recipient_phone
        else:
            clean_digits = "".join(ch for ch in recipient_phone if ch.isdigit())
            chat_id = f"{clean_digits}@c.us"
            logger.warning(
                f"send_message received a bare phone number ({recipient_phone}); "
                f"reconstructed chatId as {chat_id}. This may fail under GOWS/LID."
            )

        payload = {
            "session": self.session_name,
            "chatId": chat_id,
            "text": text
        }

        # Record message in memory buffer
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "payload": payload
        })

        # If WAHA is configured and not running in local test mode
        if not self.base_url.startswith("http://localhost") or self.api_key != "placeholder_waha_api_key":
            try:
                headers = {
                    "Content-Type": "application/json",
                    "X-Api-Key": self.api_key
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        f"{self.base_url}/api/sendText",
                        json=payload,
                        headers=headers
                    )
                    if response.status_code in (200, 201):
                        logger.info(f"WAHA message successfully dispatched to {chat_id}.")
                        return True
                    else:
                        logger.warning(
                            f"WAHA responded with status {response.status_code}: {response.text}"
                        )
                        return False
            except Exception as e:
                logger.warning(f"Unable to reach live WAHA endpoint ({e}). Recorded in memory buffer.")
                return False

        logger.debug(f"[Mock WAHA] Simulated outbound message to {chat_id}: {text[:60]}...")
        return True
