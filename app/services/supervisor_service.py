"""
Supervisor management and identity verification service.
Enforces the Zero-Trust security model by authenticating supervisors via the
SUPERVISORES Google Sheet, matched on normalized phone number (8 local
digits, no country code). Also handles the REGISTRO self-onboarding command
for phones that the administrator has already pre-loaded (Telefono/Nombre/Sede/Activo).
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.utils.phone import normalize_phone
from app.sheets.supervisors_repository import SupervisorsRepository

logger = logging.getLogger(__name__)


class SupervisorService:
    def __init__(self, repo: Optional[SupervisorsRepository] = None):
        self.repo = repo or SupervisorsRepository()

    def authenticate(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Authenticates an incoming supervisor by their normalized phone
        number. Returns the SUPERVISORES row (dict) if found and Activo,
        else None. Independent of whether they've ever run REGISTRO.
        """
        row = self.repo.find_by_phone(phone)
        if not row:
            return None
        if not self._is_active(row):
            return None
        return row

    def get_all_active(self) -> List[Dict[str, Any]]:
        """Returns all active supervisors."""
        return [row for row in self.repo.read_all() if self._is_active(row)]

    def register_supervisor(self, phone: str, from_raw: str) -> Tuple[str, Optional[str]]:
        """
        Handles the REGISTRO command for a phone already whitelisted in
        SUPERVISORES. Returns (status, nombre):
        - ("NOT_ALLOWED", None): phone not in SUPERVISORES at all.
        - ("INCOMPLETE_ROW", None): row exists but Nombre or Sede is empty.
        - ("ALREADY_REGISTERED", nombre): WhatsApp_ID was already captured.
        - ("SUCCESS", nombre): WhatsApp_ID just captured for the first time.
        """
        phone_norm = normalize_phone(phone)
        row = self.repo.find_by_phone(phone_norm)
        if row is None:
            return ("NOT_ALLOWED", None)
        if not row.get("Nombre") or not row.get("Sede"):
            return ("INCOMPLETE_ROW", None)
        if row.get("WhatsApp_ID"):
            return ("ALREADY_REGISTERED", row["Nombre"])
        self.repo.update_row_by_phone(
            phone_norm,
            WhatsApp_ID=from_raw,
            Activo="TRUE",
        )
        return ("SUCCESS", row["Nombre"])

    @staticmethod
    def _is_active(row: Dict[str, Any]) -> bool:
        return str(row.get("Activo", "")).strip().upper() == "TRUE"
