"""
Unit tests for the code-only (código de vendedor) planning flow (Part 10.4).
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
from app.whatsapp.templates import MSG_SELLER_NO_ROUTE_TODAY, MSG_SELLER_CODE_NOT_FOUND

# Miércoles 16:00 -> fecha operativa Jueves (4-JU)
EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)

SUPERVISORS = [
    {"Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]

MASTER_ROWS = [
    # 4364: una sola ruta el jueves
    {"RUTA": "SC-RUTA-1", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR UNO", "CODIGO ERP": "4364", "CODIGO RUTA": "R1"},
    # 4140: tres rutas el jueves (ambigüedad)
        {"RUTA": "SC-RUTA-2", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R2"},
    {"RUTA": "SC-RUTA-3", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R3"},
    {"RUTA": "SC-RUTA-4", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R4"},
    # 1691: existe pero no tiene ruta el jueves (solo viernes)
    {"RUTA": "SC-RUTA-5", "ZONA": "N", "DIA": "5-VI", "VENDEDOR": "VENDEDOR TRES", "CODIGO ERP": "1691", "CODIGO RUTA": "R5"},
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
async def test_single_route_shows_confirmation_summary(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4364"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 1
    assert "CONFIRMA TU PLANIFICACIÓN" in mock_wa.sent_messages[0]["text"]
    assert "VENDEDOR UNO" in mock_wa.sent_messages[0]["text"]

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"


@pytest.mark.asyncio
async def test_multiple_routes_same_day_triggers_selection(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4140"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 1
    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_SELECTION"
    assert len(entry["payload"]["candidates"]) == 3


@pytest.mark.asyncio
async def test_seller_without_route_today(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("1691"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 1
    assert mock_wa.sent_messages[0]["text"] == MSG_SELLER_NO_ROUTE_TODAY


@pytest.mark.asyncio
async def test_seller_code_not_found(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("9999"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 1
    assert mock_wa.sent_messages[0]["text"] == MSG_SELLER_CODE_NOT_FOUND
