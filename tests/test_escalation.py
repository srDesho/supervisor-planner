"""
Unit tests for the escalation event (PENDIENTE_ESCALADO flag rows + admin alert).
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.services.reminder_service import ReminderService
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp.templates import MSG_REGISTERED_OK

SUPERVISORS = [
    {"Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Telefono": "70000002", "Nombre": "Maria Suarez", "Sede": "CBBA", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]


def _dt(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=BOLIVIA_TZ)


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    return ReminderService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        supervisors_repo=SupervisorsRepository(client=fake_sheets)
    )


def _make_planning_service(fake_sheets, mock_wa):
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
async def test_escalation_marks_pending_and_alerts_admin(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(14, 18, 0))

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

    await svc.run_reminder_cycle(eval_time=_dt(14, 18, 0))

    assert len(mock_wa.sent_messages) == 0
    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert all(r["Estado"] != "PENDIENTE_ESCALADO" for r in records)


@pytest.mark.asyncio
async def test_escalation_twice_in_a_row_creates_no_duplicates(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc._run_escalation(_dt(14, 18, 0))
    first_rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    await svc._run_escalation(_dt(14, 18, 0))
    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")

    assert len(rows) == 2
    assert rows == first_rows  # same rows, same IDs, untouched
    assert len({r["ID_Registro"] for r in rows}) == 2
    assert len(mock_wa.sent_messages) == 1  # a single admin alert


@pytest.mark.asyncio
async def test_repeated_escalation_ticks_through_the_evening_stay_idempotent(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    for hour, minute in [(18, 0), (18, 30), (19, 0), (21, 30), (23, 30)]:
        await svc.run_reminder_cycle(eval_time=_dt(14, hour, minute))

    assert len(fake_sheets.get_all_records("PLANIFICACION_DIARIA")) == 2
    assert len(mock_wa.sent_messages) == 1


@pytest.mark.asyncio
async def test_escalation_never_overwrites_a_real_planning(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.sheets_repo.upsert("2026-09-15", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})

    await svc.run_reminder_cycle(eval_time=_dt(14, 18, 0))

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    carlos = [r for r in rows if r["Supervisor"] == "Carlos Mendoza"]
    assert len(carlos) == 1 and carlos[0]["Estado"] == "REGISTRADO"
    assert "Carlos Mendoza" not in mock_wa.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_escalated_supervisor_is_still_reminded_next_morning(fake_sheets):
    """Friday 18:00 escalation (for Saturday) must not silence Saturday's reminders."""
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(18, 18, 0))
    assert len(mock_wa.sent_messages) == 1  # admin alert only

    await svc.run_reminder_cycle(eval_time=_dt(19, 8, 0))

    reminders = [m for m in mock_wa.sent_messages if "Aún no hemos recibido" in m["text"]]
    assert len(reminders) == 2
    assert all("19/09/2026" in m["text"] for m in reminders)


@pytest.mark.asyncio
async def test_escalated_supervisor_can_plan_normally(fake_sheets):
    """A PENDIENTE_ESCALADO row is a flag, not a plan: no 'replace' notice, registered as new."""
    mock_wa = WhatsAppClient()
    reminders = _make_service(fake_sheets, mock_wa)
    await reminders.run_reminder_cycle(eval_time=_dt(18, 18, 0))  # Friday: escalate Saturday

    planning = _make_planning_service(fake_sheets, mock_wa)
    sat_am = _dt(19, 9, 0)

    # Garbage text is not silenced as "already registered": the supervisor gets the main menu.
    await planning.handle_message(_msg("hola", "m0"), eval_datetime=sat_am)
    assert "¿Qué quieres registrar para el sábado 19/09?" in mock_wa.sent_messages[-1]["text"]

    await planning.handle_message(_msg("oficina", "m1"), eval_datetime=sat_am)
    summary = mock_wa.sent_messages[-1]["text"]
    assert "CONFIRMA TU PLANIFICACIÓN" in summary
    assert "reemplazar" not in summary

    await planning.handle_message(_msg("confirmar", "m2"), eval_datetime=sat_am)
    assert mock_wa.sent_messages[-1]["text"] == MSG_REGISTERED_OK

    rows = [r for r in fake_sheets.get_all_records("PLANIFICACION_DIARIA") if r["Supervisor"] == "Carlos Mendoza"]
    assert len(rows) == 1  # the flag row was reused, not duplicated
    assert rows[0]["Estado"] == "REGISTRADO"
    assert rows[0]["Es_Cambio"] == "FALSE"
    assert rows[0]["Modalidad"] == "OFICINA"
    assert rows[0]["Fecha_Trabajo"] == "2026-09-19"
