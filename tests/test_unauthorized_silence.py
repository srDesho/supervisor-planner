"""
Unit tests for total silence toward unauthorized (non-whitelisted) phones (Part 10.2).
Not in SUPERVISORES + any message other than REGISTRO => zero trace: no
reply, no LOG_BOT entry, no registro_intentos.json entry.
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

EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)  # dentro de ventana

SUPERVISORS = []  # nadie registrado: cualquier teléfono está "fuera"


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


def _msg(body):
    return ParsedWhatsAppMessage(event="message", session="default", message_id="m1", from_phone="79999999", body=body)


@pytest.mark.parametrize("body", ["hola", "4140", "CONFIRMAR", "AYUDA"])
@pytest.mark.asyncio
async def test_unauthorized_phone_is_totally_silent(fake_sheets, isolated_register_log, body):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg(body), eval_datetime=EVAL_DT)

    assert len(mock_wa.sent_messages) == 0
    assert fake_sheets.get_all_records("LOG_BOT") == []
    assert not isolated_register_log.exists()
