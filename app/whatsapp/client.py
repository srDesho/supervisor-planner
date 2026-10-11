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
    MAX_SENT_MESSAGES_KEPT = 500

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
        # In-memory sent message log for testing and auditing. This client is a
        # process-wide singleton, so the log is capped (oldest entries dropped).
        self.sent_messages: List[Dict[str, Any]] = []

    async def send_message(self, recipient_phone: str, text: str) -> bool:
        """
        Sends a WhatsApp text message via WAHA.

        `recipient_phone` is either:
        - a full chatId (contains '@'), used as-is — replies to an inbound
          message reuse the sender's chatId (e.g. '{lid}@lid') unchanged; or
        - a bare phone number (proactive sends: reminders, admin alerts),
          which is turned into '{digits}@c.us': non-digits are stripped and,
          if 8 digits remain, the Bolivian country code '591' is prepended.

        NOTE: recipient_phone is coerced to str defensively because Google
        Sheets (gspread) returns numeric phone cells as int, not str.
        """
        # Defensive: gspread may return numeric cells as int/float.
        recipient_phone = str(recipient_phone)

        if "@" in recipient_phone:
            chat_id = recipient_phone
        else:
            digits = "".join(ch for ch in recipient_phone if ch.isdigit())
            if len(digits) == 8:
                digits = f"591{digits}"
            chat_id = f"{digits}@c.us"

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
        if len(self.sent_messages) > self.MAX_SENT_MESSAGES_KEPT:
            del self.sent_messages[:-self.MAX_SENT_MESSAGES_KEPT]

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
