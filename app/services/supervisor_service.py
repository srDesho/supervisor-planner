"""
Supervisor management and identity verification service.
Enforces the Zero-Trust security model by authenticating supervisors via the
SUPERVISORES Google Sheet, matched on normalized phone number (8 local
digits, no country code). The administrator pre-loads Nombre/Telefono/Sede/
Zona/Activo; supervisors never self-register.
"""
import logging
from typing import Any, Dict, List, Optional

from app.sheets.supervisors_repository import SupervisorsRepository

logger = logging.getLogger(__name__)


class SupervisorService:
    def __init__(self, repo: Optional[SupervisorsRepository] = None):
        self.repo = repo or SupervisorsRepository()

    def authenticate(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Authenticates an incoming supervisor by their normalized phone
        number. Returns the SUPERVISORES row (dict) if found and Activo,
        else None.
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

    @staticmethod
    def _is_active(row: Dict[str, Any]) -> bool:
        return str(row.get("Activo", "")).strip().upper() == "TRUE"
