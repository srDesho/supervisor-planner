"""
Google Sheets Master Catalogs manager.
Maintains in-memory cached copies of the 3 regional catalogs:
- PLANIFICACION_SCZ_RENOM (SCZ)
- PLANIFICACION_LPZ (LPZ — contains both La Paz and El Alto, distinguished
  only by the ZONA column; the bot never filters by ZONA, it reads the
  whole sheet)
- PLANIFICACION_CBBA_RENOM (CBBA)
Provides fast lookups and seed sample data for development/testing when offline.
"""

import logging
import time
from typing import Dict, List, Any, Optional

from app.config import get_settings
from .client import GoogleSheetsClient, GoogleSheetsError

logger = logging.getLogger(__name__)

# Columns we care about from the sheets
_REQUIRED_COLUMNS = {"RUTA", "ZONA", "DIA", "VENDEDOR", "CODIGO ERP", "CODIGO RUTA"}

# Static reference of sede -> worksheet name (actual sheet names are read
# from settings; this mirrors those defaults for quick lookup/tests).
SEDE_TO_WORKSHEET = {
    "SCZ": "PLANIFICACION_SCZ_RENOM",
    "CBBA": "PLANIFICACION_CBBA_RENOM",
    "LPZ": "PLANIFICACION_LPZ",
}

class MastersService:
    def __init__(self, client: Optional[GoogleSheetsClient] = None):
        # Sheets client used by refresh(); None -> the shared singleton client.
        self._client = client
        # In-memory cache: sede -> list of row dicts
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        # 0 forces staleness on first access, so the cache is populated
        # lazily from Google Sheets the first time it's queried.
        self._last_refresh: float = 0.0

    def _is_cache_stale(self) -> bool:
        # An empty cache is always stale, regardless of TTL.
        if not self._cache or all(len(v) == 0 for v in self._cache.values()):
            return True
        settings = get_settings()
        return (time.time() - self._last_refresh) > settings.SHEETS_CACHE_TTL_SECONDS

    def ensure_loaded(self) -> bool:
        """
        Forces a refresh if the cache is empty or stale.
        Never raises: logs the error and returns False on failure.
        """
        if not self._is_cache_stale():
            return True
        try:
            self.refresh()
            return True
        except Exception as exc:
            logger.error("MastersService.ensure_loaded failed: %s", exc)
            return False

    def get_master_for_sede(self, sede: str) -> List[Dict[str, Any]]:
        """Return the list of master records for a given regional sede.
        If the cache is stale, a refresh from Google Sheets is attempted.
        """
        normalized = sede.strip().upper()
        if self._is_cache_stale():
            logger.info("Master cache stale (TTL exceeded); refreshing from Google Sheets.")
            try:
                self.refresh()
            except GoogleSheetsError as exc:
                logger.error("Failed to refresh masters from Sheets: %s", exc)
                # Keep existing cache (may be empty) and continue.
        return self._cache.get(normalized, [])

    def get_masters_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return a shallow copy of the internal cache.
        The caller should treat the returned dict as read‑only.
        """
        return {k: list(v) for k, v in self._cache.items()}

    def update_cache(self, sede: str, rows: List[Dict[str, Any]]) -> None:
        """Updates the in‑memory cache for a specific sede.
        The supplied rows are stored as‑is after filtering to the required
        columns.
        """
        normalized = sede.strip().upper()
        self._cache[normalized] = rows
        self._last_refresh = time.time()
        logger.info("Updated cache for sede '%s' with %d entries.", normalized, len(rows))

    def _load_sheet(self, client: GoogleSheetsClient, sheet_name: str) -> List[Dict[str, Any]]:
        """Fetch all records from a worksheet and keep only the required columns.
        Missing columns are ignored; extra columns are dropped.
        """
        raw_records = client.get_all_records(sheet_name)
        filtered = []
        for rec in raw_records:
            filtered.append({k: v for k, v in rec.items() if k in _REQUIRED_COLUMNS})
        logger.debug(
            "Loaded %d records from worksheet '%s' (filtered to %d columns).",
            len(filtered),
            sheet_name,
            len(_REQUIRED_COLUMNS),
        )
        return filtered

    def refresh(self) -> None:
        """Refreshes the master data from the configured Google Sheets.
        All three regional sheets are read and the cache is replaced.
        """
        settings = get_settings()
        if self._client is not None:
            client = self._client
        else:
            from app.core.singletons import get_sheets_client
            client = get_sheets_client()
        if not client.is_connected:
            raise GoogleSheetsError("GoogleSheetsClient is not connected – check credentials.")

        sheet_map = {
            "SCZ": settings.GOOGLE_WORKSHEET_SCZ,
            "LPZ": settings.GOOGLE_WORKSHEET_LPZ,
            "CBBA": settings.GOOGLE_WORKSHEET_CBBA,
        }
        for sede, ws_name in sheet_map.items():
            rows = self._load_sheet(client, ws_name)
            self.update_cache(sede, rows)

        counts = {sede: len(rows) for sede, rows in self._cache.items()}
        logger.info("Masters refreshed: %s", counts)

        for sede, rows in self._cache.items():
            if not rows:
                logger.warning("Masters: sede '%s' returned 0 rows. Check worksheet name and permissions.", sede)

        self._last_refresh = time.time()
        logger.info(
            "Masters cache refreshed from Google Sheets (sedes: %s).",
            ", ".join(sheet_map.keys()),
        )

    # Backward‑compatible alias used by the test script.
    def refresh_all(self) -> None:
        self.refresh()

    def get_seller_by_code(self, sede: str, codigo_erp: str) -> List[Dict[str, Any]]:
        """Returns every master row for `sede` whose CODIGO ERP matches `codigo_erp`."""
        target = str(codigo_erp).strip()
        return [
            row for row in self.get_master_for_sede(sede)
            if str(row.get("CODIGO ERP", "")).strip() == target
        ]

    def get_seller_by_code_and_zone(
        self, sede: str, codigo_erp: str, zona: str
    ) -> List[Dict[str, Any]]:
        """Returns every master row for `sede` matching CODIGO ERP and ZONA (case-insensitive)."""
        target_code = str(codigo_erp).strip().upper()
        target_zone = str(zona).strip().upper()
        return [
            row for row in self.get_master_for_sede(sede)
            if str(row.get("CODIGO ERP", "")).strip().upper() == target_code
            and str(row.get("ZONA", "")).strip().upper() == target_zone
        ]

    def get_routes_for_seller_on_day(
        self, sede: str, codigo_erp: str, dia_codigo: str
    ) -> List[Dict[str, Any]]:
        """Returns the seller's route rows for `sede` on the given day code (e.g. '5-VI')."""
        target_day = str(dia_codigo).strip()
        return [
            row for row in self.get_seller_by_code(sede, codigo_erp)
            if str(row.get("DIA", "")).strip() == target_day
        ]

    def get_route_by_codigo(self, sede: str, codigo_ruta: str) -> Optional[Dict[str, Any]]:
        """Returns the first master row for `sede` whose CODIGO RUTA matches `codigo_ruta`."""
        target = str(codigo_ruta).strip()
        for row in self.get_master_for_sede(sede):
            if str(row.get("CODIGO RUTA", "")).strip() == target:
                return row
        return None

    def get_routes_by_zone_and_day(
        self, sede: str, zona: str, dia: str
    ) -> List[Dict[str, Any]]:
        """
        Returns every master row of `sede` with ZONA == `zona` (case-insensitive)
        and DIA == `dia` (e.g. '1-LU'), excluding market routes (RUTA containing
        'MERC'). Sorted by CODIGO RUTA ascending, numerically (non-numeric
        codes go last). Rows without a seller are included.
        """
        target_zone = str(zona).strip().upper()
        target_day = str(dia).strip()
        rows = [
            row for row in self.get_master_for_sede(sede)
            if str(row.get("ZONA", "")).strip().upper() == target_zone
            and str(row.get("DIA", "")).strip() == target_day
            and "MERC" not in str(row.get("RUTA", "")).upper()
        ]

        def sort_key(row: Dict[str, Any]):
            code = str(row.get("CODIGO RUTA", "")).strip()
            return (0, int(code), "") if code.isdigit() else (1, 0, code)

        return sorted(rows, key=sort_key)

    def get_route_by_code(
        self, sede: str, zona: str, dia: str, codigo_ruta: str
    ) -> Optional[Dict[str, Any]]:
        """
        Returns the route row whose CODIGO RUTA matches `codigo_ruta` within the
        same set as get_routes_by_zone_and_day (zone, day, no 'MERC'), or None.
        """
        target = str(codigo_ruta).strip()
        for row in self.get_routes_by_zone_and_day(sede, zona, dia):
            if str(row.get("CODIGO RUTA", "")).strip() == target:
                return row
        return None

# Backward‑compatible singleton and helper functions for test script
_service = MastersService()

def get_masters_cache() -> Dict[str, List[Dict[str, Any]]]:
    """Return a shallow copy of the masters cache.

    Used by scripts/verify_sheets.py for compatibility.
    """
    return _service.get_masters_cache()

def refresh_masters_cache() -> None:
    """Force a refresh of the masters cache from Google Sheets."""
    _service.refresh()
