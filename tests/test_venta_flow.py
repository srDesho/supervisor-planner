"""
Tests for the planning commands after REGISTRO was removed:
- parser evaluation order (VENTA DIRECTA before VENTA, code, etc.)
- VENTA flow (AWAITING_VENTA_CODE) reusing the seller-code validations
- authenticated supervisors never self-register; unknown phones stay silent
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.whatsapp.parser import ParsedWhatsAppMessage, extract_planning_intent
from app.whatsapp.client import WhatsAppClient
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.sheets.masters import MastersService
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.whatsapp.templates import (
    MSG_HELP,
    MSG_VENTA_ASK_CODE,
    MSG_VENTA_CODE_INVALID,
    MSG_CANCELLED_NO_CHANGES,
    MSG_SELLER_CODE_NOT_FOUND,
    MSG_SELLER_WRONG_ZONE,
    MSG_SELLER_ALREADY_ASSIGNED,
)

# Miércoles 16:00 -> fecha operativa Jueves (4-JU)
EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)

SUPERVISORS = [
    {"Nombre": "Carlos Mendoza", "Telefono": "70000001", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Nombre": "Maria Suarez", "Telefono": "70000002", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Nombre": "Inactivo", "Telefono": "70000003", "Sede": "SCZ", "Zona": "N", "Activo": "FALSE", "Ultimo_Recordatorio": ""},
]

MASTER_ROWS = [
    {"RUTA": "SC-RUTA-1", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR UNO", "CODIGO ERP": "4364", "CODIGO RUTA": "R1"},
    {"RUTA": "SC-RUTA-2", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R2"},
    {"RUTA": "SC-RUTA-3", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R3"},
    {"RUTA": "SC-RUTA-9", "ZONA": "S", "DIA": "4-JU", "VENDEDOR": "VENDEDOR SUR", "CODIGO ERP": "7777", "CODIGO RUTA": "R9"},
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


def _msg(body, phone="70000001", message_id="m1"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone=phone, body=body)


# --- parser ---

@pytest.mark.parametrize("text,expected", [
    ("4521", "code_only"),
    ("  4521  ", "code_only"),
    ("VENTA", "venta"),
    ("  venta  ", "venta"),
    ("Venta", "venta"),
    ("VENTA DIRECTA", "venta_directa"),
    ("venta   directa", "venta_directa"),
    ("  Venta Directa ", "venta_directa"),
    ("OFICINA", "oficina"),
    ("Oficína", "oficina"),
    ("ayuda", "help"),
    ("HELP", "help"),
    ("CONFIRMAR", "confirm"),
    ("corregir", "correct"),
    ("CANCELAR", "cancel"),
    ("REGISTRO", "unknown"),
    ("ventas", "unknown"),
    ("hola", "unknown"),
])
def test_intent_parsing(text, expected):
    assert extract_planning_intent(text)["type"] == expected


def test_code_intent_extracts_code():
    assert extract_planning_intent(" 4521 ")["codigo_erp"] == "4521"


# --- no more REGISTRO ---

@pytest.mark.asyncio
async def test_registro_is_just_an_unknown_message_for_authenticated_supervisor(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("REGISTRO"), eval_datetime=EVAL_DT)

    assert [m["text"] for m in mock_wa.sent_messages] == [MSG_HELP]
    assert all(r["accion"] != "SELF_REGISTER" for r in fake_sheets.get_all_records("LOG_BOT"))


@pytest.mark.asyncio
async def test_inactive_supervisor_is_silent(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA", phone="70000003"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages == []
    assert fake_sheets.get_all_records("LOG_BOT") == []


# --- VENTA flow ---

@pytest.mark.asyncio
async def test_venta_asks_for_code_and_enters_awaiting_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA"), eval_datetime=EVAL_DT)

    assert [m["text"] for m in mock_wa.sent_messages] == [MSG_VENTA_ASK_CODE]
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_VENTA_CODE"


@pytest.mark.asyncio
async def test_venta_code_proposes_venta_plan_and_confirm_writes_sheet(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("venta"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4364", message_id="m2"), eval_datetime=EVAL_DT)

    summary = mock_wa.sent_messages[-1]["text"]
    assert "CONFIRMA TU PLANIFICACIÓN" in summary
    assert "VENTA" in summary and "👤 VENDEDOR UNO" in summary
    assert "Vendedor:" not in summary

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "VENTA"
    assert entry["payload"]["draft"]["vendedor_apoyo"] == ""

    await svc.handle_message(_msg("CONFIRMAR", message_id="m3"), eval_datetime=EVAL_DT)

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(rows) == 1
    assert rows[0]["Modalidad"] == "VENTA"
    assert rows[0]["Vendedor_Apoyo"] == ""
    assert rows[0]["Codigo_ERP_Vendedor"] == "4364"
    assert rows[0]["Ruta_Oficial"] == "SC-RUTA-1"


@pytest.mark.asyncio
async def test_code_alone_still_means_acompanamiento(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4364"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("CONFIRMAR", message_id="m2"), eval_datetime=EVAL_DT)

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert rows[0]["Modalidad"] == "ACOMPAÑAMIENTO"
    assert rows[0]["Vendedor_Apoyo"] == "VENDEDOR UNO"


@pytest.mark.asyncio
async def test_venta_with_multiple_routes_goes_through_selection_keeping_modalidad(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4140", message_id="m2"), eval_datetime=EVAL_DT)
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_SELECTION"

    await svc.handle_message(_msg("2", message_id="m3"), eval_datetime=EVAL_DT)

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "VENTA"
    assert entry["payload"]["draft"]["codigo_ruta"] == "R3"


@pytest.mark.asyncio
async def test_venta_cancel_exits_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("CANCELAR", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None


@pytest.mark.asyncio
async def test_venta_invalid_input_keeps_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("oficina", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_VENTA_CODE_INVALID
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_VENTA_CODE"


@pytest.mark.asyncio
async def test_venta_unknown_code_keeps_state_for_retry(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("9999", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_SELLER_CODE_NOT_FOUND
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_VENTA_CODE"


@pytest.mark.asyncio
async def test_venta_wrong_zone_is_rejected(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("7777", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_SELLER_WRONG_ZONE.format(
        codigo="7777", vendedor="VENDEDOR SUR", zona_vendedor="S"
    )
    records = fake_sheets.get_all_records("LOG_BOT")
    assert records[-1]["accion"] == "REJECTED_WRONG_ZONE"


@pytest.mark.asyncio
async def test_venta_duplicate_seller_names_the_seller_not_na(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    # Maria registers VENTA on 4364 first (Vendedor_Apoyo is empty in the Sheet).
    await svc.handle_message(_msg("VENTA", phone="70000002"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4364", phone="70000002", message_id="m2"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("CONFIRMAR", phone="70000002", message_id="m3"), eval_datetime=EVAL_DT)

    # Carlos now tries the same seller.
    await svc.handle_message(_msg("VENTA", phone="70000001", message_id="m4"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4364", phone="70000001", message_id="m5"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_SELLER_ALREADY_ASSIGNED.format(
        vendedor="VENDEDOR UNO", fecha="17/09/2026", otro_supervisor="Maria Suarez"
    )


@pytest.mark.asyncio
async def test_venta_directa_not_confused_with_venta(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA DIRECTA"), eval_datetime=EVAL_DT)

    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"
    assert svc.conversation_svc.get("70000001")["payload"]["draft"]["modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_new_venta_while_awaiting_confirmation_restarts_flow(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("OFICINA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("VENTA", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_VENTA_ASK_CODE
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_VENTA_CODE"
