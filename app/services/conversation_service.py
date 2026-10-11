"""
Conversation context and transient state management service.

Estado en memoria. Se pierde al reiniciar el proceso. Aceptado como
limitación del MVP (si el bot se reinicia a mitad de una conversación,
el supervisor simplemente reenvía su mensaje).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Estado compartido por todas las instancias del proceso:
# {chat_id: {"state": str, "payload": dict, "expires_at": datetime}}
_STORE: Dict[str, Dict[str, Any]] = {}


class ConversationService:
    def __init__(self):
        self.settings = get_settings()

    def get(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Devuelve la entrada de chat_id, auto-limpiándola si ya expiró."""
        entry = _STORE.get(chat_id)
        if not entry:
            return None
        if datetime.now(timezone.utc) > entry["expires_at"]:
            self.clear(chat_id)
            return None
        return entry

    def set(
        self,
        chat_id: str,
        state: str,
        payload: Optional[Dict[str, Any]] = None,
        ttl_minutes: Optional[int] = None
    ) -> None:
        ttl = ttl_minutes if ttl_minutes is not None else self.settings.CONVERSATION_TTL_MINUTES
        _STORE[chat_id] = {
            "state": state,
            "payload": payload or {},
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=ttl)
        }

    def clear(self, chat_id: str) -> None:
        _STORE.pop(chat_id, None)

    def clear_expired(self) -> int:
        """Elimina todas las entradas expiradas del proceso. Devuelve cuántas se limpiaron."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in _STORE.items() if now > v["expires_at"]]
        for k in expired:
            _STORE.pop(k, None)
        if expired:
            logger.debug(f"Cleared {len(expired)} expired conversation state(s).")
        return len(expired)
