"""
Unit tests for the full planning confirmation flow (Part 10.5).
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

EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)  # Miércoles -> Jueves (4-JU)

SUPERVISORS = [
    {"WhatsApp_ID": "", "Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()
    return PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        masters_service=MastersService(),
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets))
    )


def _msg(body, message_id="m1"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone="70000001", body=body)


@pytest.mark.asyncio
async def test_venta_directa_fields_are_na(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("venta directa"), eval_datetime=EVAL_DT)
    entry = svc.conversation_svc.get("70000001")
    draft = entry["payload"]["draft"]

    assert draft["modalidad"] == "VENTA DIRECTA"
    assert draft["vendedor_apoyo"] == "VENTA DIRECTA"
    assert draft["codigo_erp_vendedor"] == "N/A"
    assert draft["ruta_oficial"] == "N/A"
    assert draft["zona"] == "N/A"
    assert draft["codigo_ruta"] == "N/A"
    assert draft["dia"] == "N/A"


@pytest.mark.asyncio
async def test_oficina_fields_are_na(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina"), eval_datetime=EVAL_DT)
    entry = svc.conversation_svc.get("70000001")
    draft = entry["payload"]["draft"]

    assert draft["modalidad"] == "OFICINA"
    assert draft["vendedor_apoyo"] == "N/A"
    assert draft["ruta_oficial"] == "N/A"


@pytest.mark.asyncio
async def test_confirm_first_time_sets_es_cambio_false(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m2"), eval_datetime=EVAL_DT)

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1
    assert records[0]["Es_Cambio"] == "FALSE"
    assert records[0]["Estado"] == "REGISTRADO"

    entry = svc.conversation_svc.get("70000001")
    assert entry is None


@pytest.mark.asyncio
async def test_second_planning_same_day_updates_same_row(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m2"), eval_datetime=EVAL_DT)
    first_id = fake_sheets.get_all_records("PLANIFICACION_DIARIA")[0]["ID_Registro"]

    await svc.handle_message(_msg("venta directa", "m3"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m4"), eval_datetime=EVAL_DT)

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1  # misma fila, no una nueva
    assert records[0]["ID_Registro"] == first_id
    assert records[0]["Es_Cambio"] == "TRUE"
    assert records[0]["Estado"] == "MODIFICADO"
    assert records[0]["Modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_correct_shows_summary_and_keeps_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("corregir", "m2"), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 2
    assert "CONFIRMA TU PLANIFICACIÓN" in mock_wa.sent_messages[1]["text"]
    assert "Envía la planificación corregida" in mock_wa.sent_messages[1]["text"]

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"


@pytest.mark.asyncio
async def test_cancel_clears_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("cancelar", "m2"), eval_datetime=EVAL_DT)

    entry = svc.conversation_svc.get("70000001")
    assert entry is None

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 0
