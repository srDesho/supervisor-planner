"""
Unit tests for the Monday-Friday escalation event (Part 10.8).
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.services.reminder_service import ReminderService
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.whatsapp.client import WhatsAppClient

SUPERVISORS = [
    {"Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Telefono": "70000002", "Nombre": "Maria Suarez", "Sede": "CBBA", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    return ReminderService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        supervisors_repo=SupervisorsRepository(client=fake_sheets)
    )


@pytest.mark.asyncio
async def test_escalation_marks_pending_and_alerts_admin(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 18, 0, tzinfo=BOLIVIA_TZ))

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 2
    assert all(r["Estado"] == "PENDIENTE_ESCALADO" for r in records)

    assert len(mock_wa.sent_messages) == 1
    assert "Carlos Mendoza" in mock_wa.sent_messages[0]["text"]
    assert "Maria Suarez" in mock_wa.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_no_escalation_alert_when_everyone_registered(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    svc.sheets_repo.upsert("2026-09-15", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})
    svc.sheets_repo.upsert("2026-09-15", "CBBA", "Maria Suarez", {"Modalidad": "OFICINA"})

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 18, 0, tzinfo=BOLIVIA_TZ))

    assert len(mock_wa.sent_messages) == 0
    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert all(r["Estado"] != "PENDIENTE_ESCALADO" for r in records)
