"""
Incoming messages are attended at ANY day/hour; only proactive reminders follow the schedule.
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp.client import WhatsAppClient
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE

OUTSIDE_WINDOW_DT = datetime(2026, 9, 16, 10, 0, tzinfo=BOLIVIA_TZ)  # Miércoles 10:00 (antes de 15:00)
SATURDAY_DT = datetime(2026, 9, 19, 11, 0, tzinfo=BOLIVIA_TZ)        # Sábado 11:00
SATURDAY_PM_DT = datetime(2026, 9, 19, 16, 0, tzinfo=BOLIVIA_TZ)     # Sábado 16:00
SUNDAY_DT = datetime(2026, 9, 20, 10, 0, tzinfo=BOLIVIA_TZ)          # Domingo 10:00

SUPERVISORS = [
    {"Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()
    return PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets))
    )


def _msg(body, message_id="m1"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone="70000001", body=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("when,expected_date", [
    (OUTSIDE_WINDOW_DT, "17/09/2026"),  # Miércoles 10:00 -> Jueves
    (SATURDAY_DT, "19/09/2026"),        # Sábado 11:00 -> Sábado
    (SATURDAY_PM_DT, "21/09/2026"),     # Sábado 16:00 -> Lunes
    (SUNDAY_DT, "21/09/2026"),          # Domingo -> Lunes
])
async def test_messages_are_attended_at_any_day_and_hour(fake_sheets, when, expected_date):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina"), eval_datetime=when)

    assert len(mock_wa.sent_messages) == 1
    assert "CONFIRMA TU PLANIFICACIÓN" in mock_wa.sent_messages[0]["text"]
    assert expected_date in mock_wa.sent_messages[0]["text"]
    records = fake_sheets.get_all_records("LOG_BOT")
    assert not [r for r in records if r.get("accion") == "OUTSIDE_WINDOW"]


@pytest.mark.asyncio
async def test_pending_confirmation_bypasses_window(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    svc.conversation_svc.set("70000001", "AWAITING_CONFIRMATION", payload={"draft": {
        "modalidad": "OFICINA", "vendedor_apoyo": "N/A", "codigo_erp_vendedor": "N/A",
        "ruta_oficial": "N/A", "zona": "N/A", "codigo_ruta": "N/A", "dia": "N/A",
        "fecha_trabajo": "2026-09-16", "sede": "SCZ", "supervisor": "Carlos Mendoza"
    }})

    await svc.handle_message(_msg("CONFIRMAR", "m2"), eval_datetime=OUTSIDE_WINDOW_DT)

    assert len(mock_wa.sent_messages) == 1
    assert "REGISTRADA" in mock_wa.sent_messages[0]["text"]

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1
