"""
Unit tests for the REGISTRO command (Part 10.1).
"""
import json
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.whatsapp.parser import ParsedWhatsAppMessage, is_register_command
from app.whatsapp.client import WhatsAppClient
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.whatsapp.templates import MSG_REGISTER_OK, MSG_ALREADY_REGISTERED, MSG_REGISTER_INCOMPLETE_ROW

EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)

SUPERVISORS = [
    {"WhatsApp_ID": "", "Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"WhatsApp_ID": "", "Telefono": "70000002", "Nombre": "", "Sede": "", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
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


def _msg(body, phone="70000001"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id="m1", from_phone=phone, body=body)


def test_is_register_command_matches_variants():
    assert is_register_command("registro") is True
    assert is_register_command("REGISTRO") is True
    assert is_register_command(" Registro! ") is True
    assert is_register_command("REGISTRAR") is False


@pytest.mark.asyncio
async def test_registro_success_saves_whatsapp_id(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("REGISTRO"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 1
    assert mock_wa.sent_messages[0]["text"] == MSG_REGISTER_OK.format(nombre="Carlos Mendoza")

    row = svc.supervisor_svc.repo.find_by_phone("70000001")
    assert row["WhatsApp_ID"] == "70000001"

    records = fake_sheets.get_all_records("LOG_BOT")
    assert len(records) == 1
    assert records[0]["accion"] == "SELF_REGISTER"
    assert records[0]["resultado"] == "SUCCESS"


@pytest.mark.asyncio
async def test_registro_second_time_already_registered(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("REGISTRO"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("REGISTRO"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[1]["text"] == MSG_ALREADY_REGISTERED.format(nombre="Carlos Mendoza")


@pytest.mark.asyncio
async def test_registro_unauthorized_phone_silent_with_json_only(fake_sheets, isolated_register_log):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("REGISTRO", phone="79999999"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 0
    assert fake_sheets.get_all_records("LOG_BOT") == []

    assert isolated_register_log.exists()
    entries = json.loads(isolated_register_log.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["telefono"] == "79999999"


@pytest.mark.asyncio
async def test_registro_incomplete_row(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("REGISTRO", phone="70000002"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[0]["text"] == MSG_REGISTER_INCOMPLETE_ROW
