"""
JSON-based logging of unauthorized REGISTRO attempts.

Numbers not present in SUPERVISORES must leave zero trace in Google Sheets
(no LOG_BOT entry, no reply) — the only record of the attempt is this local
JSON file, for the admin to review manually.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def log_unauthorized_register_attempt(whatsapp_id: str, telefono: str, mensaje: str) -> None:
    """Appends one entry to REGISTER_ATTEMPTS_LOG_PATH. Never raises."""
    settings = get_settings()
    path = Path(settings.REGISTER_ATTEMPTS_LOG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        entries = []
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)

        entries.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "whatsapp_id": whatsapp_id,
            "telefono": telefono,
            "mensaje": mensaje
        })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to log unauthorized register attempt to {path}: {e}")
