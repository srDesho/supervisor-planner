"""
Planning repository for Google Sheets (PLANIFICACION_DIARIA).
Implements find_active, upsert and cancel over the consolidated output sheet.
Never caches: always reads fresh before writing, so a UPSERT never overwrites
concurrent state with stale data, and never creates two active rows for the
same logical key (fecha_trabajo, sede, supervisor).
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.config import get_settings
from .client import GoogleSheetsClient, GoogleSheetsError

logger = logging.getLogger(__name__)

# Flag row created by the escalation cycle for a supervisor who did not plan
# in time. It is NOT a real planning: see is_real_planning().
ESCALATED_STATE = "PENDIENTE_ESCALADO"


def is_real_planning(row: Optional[Dict[str, Any]]) -> bool:
    """True if `row` (from find_active) is an actual planning, not an escalation flag."""
    return row is not None and row.get("Estado") != ESCALATED_STATE

# Column order as defined in SPEC.md §30
_COLUMNS = [
    "ID_Registro",
    "Fecha_Registro",
    "Hora_Registro",
    "Fecha_Trabajo",
    "Sede",
    "Supervisor",
    "Modalidad",
    "Vendedor_Apoyo",
    "Codigo_ERP_Vendedor",
    "Ruta_Oficial",
    "Zona",
    "Codigo_Ruta",
    "DIA",
    "Estado",
    "Observaciones",
    "Es_Cambio",
    "ID_Mensaje_WA",
]


class GoogleSheetsPlanningRepository:
    def __init__(self, client: Optional[GoogleSheetsClient] = None):
        # Default to the shared singleton, never a fresh instance (see app/core/singletons.py).
        from app.core.singletons import get_sheets_client
        self.client = client or get_sheets_client()
        if not self.client.is_connected:
            raise GoogleSheetsError("GoogleSheetsClient not connected – check credentials.")
        settings = get_settings()
        self.worksheet_name = settings.GOOGLE_OUTPUT_WORKSHEET

    def _row_to_values(self, payload: Dict[str, Any]) -> List[Any]:
        """Convert payload dict to ordered list matching _COLUMNS.
        Missing keys are filled with empty strings. Date and time fields are
        defaulted to current values when not supplied.
        """
        now = datetime.now()

        def fmt(key: str, fmt_str: str) -> str:
            return payload.get(key) or now.strftime(fmt_str)

        values: List[Any] = []
        for col in _COLUMNS:
            if col == "Fecha_Registro":
                values.append(fmt(col, "%d/%m/%Y"))
            elif col == "Hora_Registro":
                values.append(fmt(col, "%H:%M:%S"))
            elif col == "ID_Registro":
                values.append(payload.get(col) or str(uuid.uuid4()))
            else:
                values.append(payload.get(col, ""))
        return values

    def find_active(self, fecha_trabajo: str, sede: str, supervisor: str) -> Optional[Dict[str, Any]]:
        """Locates an active (non-CANCELADO) planning row for the logical key.
        Returns the row dict plus a special ``__row_index`` (1-based sheet row).
        """
        records = self.client.get_all_records(self.worksheet_name)
        for idx, row in enumerate(records, start=2):  # header is row 1
            if (
                row.get("Fecha_Trabajo") == fecha_trabajo
                and row.get("Sede") == sede
                and row.get("Supervisor") == supervisor
                and row.get("Estado") != "CANCELADO"
            ):
                result = dict(row)
                result["__row_index"] = idx
                return result
        return None

    def find_seller_duplicate(
        self,
        fecha_trabajo: str,
        codigo_erp_vendedor: str,
        exclude_supervisor: str,
        sede: str
    ) -> Optional[Dict[str, Any]]:
        """
        Searches PLANIFICACION_DIARIA for rows with:
        - Fecha_Trabajo == fecha_trabajo
        - Codigo_ERP_Vendedor == codigo_erp_vendedor
        - Sede == sede
        - Supervisor != exclude_supervisor
        - Estado != "CANCELADO"
        Returns the first matching row or None.
        """
        records = self.client.get_all_records(self.worksheet_name)
        target_code = str(codigo_erp_vendedor).strip()
        for idx, row in enumerate(records, start=2):
            if (
                row.get("Fecha_Trabajo") == fecha_trabajo
                and str(row.get("Codigo_ERP_Vendedor", "")).strip() == target_code
                and row.get("Sede") == sede
                and row.get("Supervisor") != exclude_supervisor
                and row.get("Estado") != "CANCELADO"
            ):
                result = dict(row)
                result["__row_index"] = idx
                return result
        return None

    def upsert(self, fecha_trabajo: str, sede: str, supervisor: str, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inserts a new planning row, or updates the existing active row for
        the same (fecha_trabajo, sede, supervisor) key. Never creates two
        active rows for the same key. Always reads fresh first.
        """
        payload = dict(datos)
        payload["Fecha_Trabajo"] = fecha_trabajo
        payload["Sede"] = sede
        payload["Supervisor"] = supervisor

        active = self.find_active(fecha_trabajo, sede, supervisor)
        if active:
            row_index = active["__row_index"]
            payload["ID_Registro"] = active.get("ID_Registro")
            if active.get("Estado") == ESCALATED_STATE:
                # First real planning after being escalated: reuse the flag
                # row, but it is a registration, not a change.
                now = datetime.now()
                payload["Es_Cambio"] = "FALSE"
                payload["Estado"] = "REGISTRADO"
                payload["Fecha_Registro"] = now.strftime("%d/%m/%Y")
                payload["Hora_Registro"] = now.strftime("%H:%M:%S")
            else:
                payload["Es_Cambio"] = "TRUE"
                payload.setdefault("Estado", "MODIFICADO")
            current_records = self.client.get_all_records(self.worksheet_name)
            current_row = current_records[row_index - 2]
            merged = {**current_row, **payload}
            values = [merged.get(col, "") for col in _COLUMNS]
            self.client.update_row(self.worksheet_name, row_index, values)
            logger.info(f"Updated planning row {merged.get('ID_Registro')} at index {row_index} in {self.worksheet_name}.")
            merged["__row_index"] = row_index
            return merged
        else:
            payload["ID_Registro"] = payload.get("ID_Registro") or str(uuid.uuid4())
            payload["Es_Cambio"] = "FALSE"
            payload.setdefault("Estado", "REGISTRADO")
            values = self._row_to_values(payload)
            self.client.append_row(self.worksheet_name, values)
            logger.info(f"Inserted new planning row {payload['ID_Registro']} into {self.worksheet_name}.")
            return dict(zip(_COLUMNS, values))

    def cancel(self, fecha_trabajo: str, sede: str, supervisor: str) -> Optional[Dict[str, Any]]:
        """Marks the active row for this key as CANCELADO. Does not delete the row."""
        active = self.find_active(fecha_trabajo, sede, supervisor)
        if not active:
            logger.info(f"cancel(): no active planning found for {fecha_trabajo}/{sede}/{supervisor}.")
            return None

        row_index = active["__row_index"]
        current_records = self.client.get_all_records(self.worksheet_name)
        current_row = current_records[row_index - 2]
        merged = {**current_row, "Estado": "CANCELADO", "Es_Cambio": "TRUE"}
        values = [merged.get(col, "") for col in _COLUMNS]
        self.client.update_row(self.worksheet_name, row_index, values)
        logger.info(f"Cancelled planning row {merged.get('ID_Registro')} at index {row_index} in {self.worksheet_name}.")
        merged["__row_index"] = row_index
        return merged

    def mark_escalated(self, fecha_trabajo: str, sede: str, supervisor: str) -> Dict[str, Any]:
        """
        Creates the PENDIENTE_ESCALADO flag row (with N/A fields) for this
        key, once. Idempotent: if ANY active row already exists for the key
        (a real planning, or a previous escalation) nothing is written and
        that row is returned. The result carries ``__created`` so callers
        know whether this call actually escalated the supervisor.
        """
        active = self.find_active(fecha_trabajo, sede, supervisor)
        if active:
            active["__created"] = False
            return active

        payload = {
            "Fecha_Trabajo": fecha_trabajo,
            "Sede": sede,
            "Supervisor": supervisor,
            "Modalidad": "N/A",
            "Vendedor_Apoyo": "N/A",
            "Codigo_ERP_Vendedor": "N/A",
            "Ruta_Oficial": "N/A",
            "Zona": "N/A",
            "Codigo_Ruta": "N/A",
            "DIA": "N/A",
            "Estado": ESCALATED_STATE,
            "Es_Cambio": "FALSE"
        }
        values = self._row_to_values(payload)
        self.client.append_row(self.worksheet_name, values)
        logger.info(f"Created PENDIENTE_ESCALADO row for {sede}/{supervisor}/{fecha_trabajo} in {self.worksheet_name}.")
        created = dict(zip(_COLUMNS, values))
        created["__created"] = True
        return created
