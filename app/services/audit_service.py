"""
Audit and operational log service.
Persists structured traces to Google Sheets (LOG_BOT). Keeps the same public
signature the rest of the codebase already calls, adapted internally to the
LOG_BOT column names.
"""
import logging
from typing import Optional

from app.sheets.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, repo: Optional[AuditRepository] = None):
        from app.core.singletons import get_audit_repo  # shared repo, see app/core/singletons.py
        self.repo = repo or get_audit_repo()

    def log(
        self,
        phone: Optional[str] = None,
        supervisor: Optional[str] = None,
        sede: Optional[str] = None,
        whatsapp_message_id: Optional[str] = None,
        original_message: Optional[str] = None,
        intent: Optional[str] = None,
        state_before: Optional[str] = None,
        state_after: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
        details: Optional[str] = None,
        whatsapp_id: Optional[str] = None
    ) -> None:
        """
        Logs an audit record to LOG_BOT and logs an informational trace to
        stdout. Never raises: a Sheets failure is logged at ERROR level and
        must never interrupt the calling flow.
        """
        try:
            self.repo.append_log({
                "telefono_resuelto": phone,
                "whatsapp_id": whatsapp_id,
                "nombre": supervisor,
                "sede": sede,
                "wa_msg_id": whatsapp_message_id,
                "mensaje_original": original_message,
                "intencion": intent,
                "estado_antes": state_before,
                "estado_despues": state_after,
                "accion": action,
                "resultado": result,
                "error": error,
                "detalles": details
            })
            logger.info(
                f"[AUDIT] phone={phone} supervisor={supervisor} action={action} result={result}"
            )
        except Exception as e:
            logger.error(f"Failed to record audit log: {e}")
