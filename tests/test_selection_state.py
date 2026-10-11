"""
Unit tests for AWAITING_SELECTION handling (Part 10.6).
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp.client import WhatsAppClient
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.sheets.masters import MastersService
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.whatsapp.templates import MSG_SELECTION_TOO_MANY_ERRORS

EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)  # Miércoles -> Jueves (4-JU)

SUPERVISORS = [
    {"WhatsApp_ID": "", "Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]

MASTER_ROWS = [
    {"RUTA": "SC-RUTA-2", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R2"},
    {"RUTA": "SC-RUTA-3", "ZONA": "S", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R3"},
    {"RUTA": "SC-RUTA-4", "ZONA": "E", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R4"},
]


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()

    masters = MastersService()
    masters.update_cache("SCZ", MASTER_ROWS)

    return PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        masters_service=masters,
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets))
    )


def _msg(body, message_id="m1"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone="70000001", body=body)


@pytest.mark.asyncio
async def test_selecting_valid_number_moves_to_awaiting_confirmation(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4140", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("2", "m2"), eval_datetime=EVAL_DT)

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["codigo_ruta"] == "R3"


@pytest.mark.asyncio
async def test_cancelar_clears_selection(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4140", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("cancelar", "m2"), eval_datetime=EVAL_DT)

    entry = svc.conversation_svc.get("70000001")
    assert entry is None


@pytest.mark.asyncio
async def test_three_invalid_attempts_clears_with_too_many_errors(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4140", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("99", "m2"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("xx", "m3"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("zz", "m4"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_SELECTION_TOO_MANY_ERRORS
    entry = svc.conversation_svc.get("70000001")
    assert entry is None
