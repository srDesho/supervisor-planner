"""
Audit log repository writing to the LOG_BOT worksheet in Google Sheets.
Always writes fresh (no caching): auditing must never serve stale data.

Auditing is a secondary concern: if Google Sheets is unreachable, this
repository logs an ERROR and returns quietly instead of raising, so it never
brings down the main planning flow (see AuditService).
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.config import get_settings
from .client import GoogleSheetsClient

logger = logging.getLogger(__name__)

LOG_BOT_COLUMNS = [
    "timestamp",
    "telefono_resuelto",
    "whatsapp_id",
    "nombre",
    "sede",
    "wa_msg_id",
    "mensaje_original",
    "intencion",
    "estado_antes",
    "estado_despues",
    "accion",
    "resultado",
    "error",
    "detalles",
]


class AuditRepository:
    def __init__(self, client: Optional[GoogleSheetsClient] = None):
        # Default to the shared singleton, never a fresh instance (see app/core/singletons.py).
        from app.core.singletons import get_sheets_client
        self.client = client or get_sheets_client()
        settings = get_settings()
        self.worksheet_name = settings.GOOGLE_WORKSHEET_LOG

    def ensure_sheet(self) -> bool:
        """
        Creates LOG_BOT with the correct headers if it doesn't exist yet.
        Returns True if it already existed, False if it was just created or
        couldn't be verified (Sheets unreachable).
        """
        if not self.client.is_connected:
            logger.error("No se pudo verificar LOG_BOT: GoogleSheetsClient no está conectado.")
            return False
        try:
            return self.client.ensure_worksheet(self.worksheet_name, LOG_BOT_COLUMNS)
        except Exception as e:
            logger.error(f"Error verificando/creando la pestaña {self.worksheet_name}: {e}")
            return False

    def append_log(self, row: Dict[str, Any]) -> None:
        """Appends one audit row to LOG_BOT. Never raises: logs ERROR on failure."""
        if not self.client.is_connected:
            logger.error(f"No se pudo escribir en LOG_BOT (Sheets desconectado): {row}")
            return
        try:
            payload = dict(row)
            payload.setdefault("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            values = [payload.get(col, "") for col in LOG_BOT_COLUMNS]
            self.client.append_row(self.worksheet_name, values)
        except Exception as e:
            logger.error(f"Failed to append audit log row to {self.worksheet_name}: {e}")
