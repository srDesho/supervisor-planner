# scripts/verify_sheets.py
"""Verification script for Google Sheets planning repository.

It connects to Google Sheets, prints master sheet counts, performs a full
CRUD flow on the planning worksheet: insert, find, update, cancel.
"""
import sys
from pathlib import Path
# Ensure the project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.sheets.client import GoogleSheetsClient
from app.sheets.masters import get_masters_cache, refresh_masters_cache
from app.sheets.planning_repository import GoogleSheetsPlanningRepository
import logging
import datetime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def main():
    settings = get_settings()
    # Show master sheet counts (reuse existing logic)
    masters = get_masters_cache()
    if not masters:
        log.info("Masters cache empty, refreshing.")
        refresh_masters_cache()
        masters = get_masters_cache()
    for sheet_name, rows in masters.items():
        log.info(f"Master sheet '{sheet_name}' rows: {len(rows)}")

    repo = GoogleSheetsPlanningRepository()
    # Build a test record matching SPEC columns
    now = datetime.datetime.now()
    test_data = {
        "ID_Registro": "TEST-000",
        "Fecha_Registro": now.strftime("%Y-%m-%d"),
        "Hora_Registro": now.strftime("%H:%M:%S"),
        "Fecha_Trabajo": (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
        "Sede": "SCZ",
        "Supervisor": "Supervisor Test",
        "Modalidad": "Presencial",
        "Vendedor_Apoyo": "Vendedor X",
        "Codigo_ERP_Vendedor": "ERP123",
        "Ruta_Oficial": "R001",
        "Zona": "Z1",
        "Codigo_Ruta": "CR001",
        "DIA": "LUNES",
        "Estado": "REGISTRADO",
        "Observaciones": "",
        "Es_Cambio": "NO",
        "ID_Mensaje_WA": "",
    }
    # Insert test planning
    inserted_id = repo.insert_planning(test_data)
    log.info(f"Inserted planning with ID_Registro={inserted_id}")
    # Find the inserted record
    record = repo.find_active_planning(
        fecha_trabajo=test_data["Fecha_Trabajo"],
        sede=test_data["Sede"],
        supervisor=test_data["Supervisor"],
    )
    if not record:
        log.error("Failed to locate inserted planning record.")
        sys.exit(1)
    log.info(f"Found planning row index: {record['__row_index']}")
    # Update to MODIFICADO
    repo.update_planning(record['__row_index'], {"Estado": "MODIFICADO", "Es_Cambio": "SI"})
    log.info("Updated planning to MODIFICADO.")
    # Cancel planning
    repo.cancel_planning(record['__row_index'])
    log.info("Cancelled planning.")
    print("OK - flujo de escritura completo")

if __name__ == "__main__":
    main()
