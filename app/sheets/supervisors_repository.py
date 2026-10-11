"""
Supervisors repository backed by the SUPERVISORES Google Sheet (whitelist).

Columnas EXACTAS (fila 1):
Nombre | Telefono | Sede | Zona | Activo | Ultimo_Recordatorio

El administrador pre-carga Nombre, Telefono, Sede, Zona, Activo=TRUE. El bot
solo escribe Ultimo_Recordatorio cuando envía un recordatorio.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.utils.phone import normalize_phone
from .client import GoogleSheetsClient, GoogleSheetsError

logger = logging.getLogger(__name__)

_COLUMNS = [
    "Nombre",
    "Telefono",
    "Sede",
    "Zona",
    "Activo",
    "Ultimo_Recordatorio",
]


class SupervisorsRepository:
    def __init__(self, client: Optional[GoogleSheetsClient] = None):
        # Default to the shared singleton, never a fresh instance (see app/core/singletons.py).
        from app.core.singletons import get_sheets_client
        self.client = client or get_sheets_client()
        if not self.client.is_connected:
            raise GoogleSheetsError("GoogleSheetsClient not connected – check credentials.")
        settings = get_settings()
        self.worksheet_name = settings.GOOGLE_WORKSHEET_SUPERVISORS
        self._cache: List[Dict[str, Any]] = []
        self._last_refresh: float = 0.0

    def _is_cache_stale(self) -> bool:
        settings = get_settings()
        return (time.time() - self._last_refresh) > settings.SUPERVISORS_CACHE_TTL_SECONDS

    def read_all(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns all supervisor rows, refreshing the in-memory cache if stale."""
        if force_refresh or self._is_cache_stale() or not self._cache:
            records = self.client.get_all_records(self.worksheet_name)
            for r in records:
                r.setdefault("Zona", "")
            self._cache = records
            self._last_refresh = time.time()
        return list(self._cache)

    def find_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Finds the first supervisor row whose Telefono normalizes to the same
        8 local digits as `phone` (e.g. '69105312' matches '59169105312').
        """
        target = normalize_phone(phone)
        if not target:
            return None
        for row in self.read_all():
            if normalize_phone(str(row.get("Telefono", ""))) == target:
                return row
        return None

    def _find_row_index_by_phone(self, phone: str) -> Optional[int]:
        target = normalize_phone(phone)
        if not target:
            return None
        records = self.client.get_all_records(self.worksheet_name)
        for idx, row in enumerate(records, start=2):  # header is row 1
            if normalize_phone(str(row.get("Telefono", ""))) == target:
                return idx
        return None

    def update_row_by_phone(self, phone: str, **cols: Any) -> Optional[Dict[str, Any]]:
        """Updates the given columns for the supervisor whose Telefono matches `phone`."""
        row_index = self._find_row_index_by_phone(phone)
        if row_index is None:
            logger.warning(f"update_row_by_phone: no supervisor found for phone {phone}")
            return None

        current_records = self.client.get_all_records(self.worksheet_name)
        current_row = current_records[row_index - 2]
        merged = {**current_row, **cols}
        values = [merged.get(col, "") for col in _COLUMNS]
        self.client.update_row(self.worksheet_name, row_index, values)
        self._last_refresh = 0.0  # force refresh on next read
        return merged

    def update_last_reminder(self, phone: str, timestamp: str) -> Optional[Dict[str, Any]]:
        """Records the last reminder sent timestamp for the given phone."""
        return self.update_row_by_phone(phone, Ultimo_Recordatorio=timestamp)
