"""
Unit tests for the reminder/escalation schedule (Part 10.7).
Lunes 14/09/2026 (Monday), Sábado 19/09/2026, Domingo 20/09/2026.
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.services.reminder_service import ReminderService
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.templates import MSG_REMINDER_SATURDAY_NOTICE

SUPERVISORS = [
    {"WhatsApp_ID": "", "Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"WhatsApp_ID": "", "Telefono": "70000002", "Nombre": "Maria Suarez", "Sede": "CBBA", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
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
async def test_monday_1500_sends_reminder_and_updates_last_reminder(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    eval_dt = datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ)  # Lunes
    await svc.run_reminder_cycle(eval_time=eval_dt)

    assert len(mock_wa.sent_messages) == 2
    row = svc.supervisors_repo.find_by_phone("70000001")
    assert row["Ultimo_Recordatorio"] == "2026-09-14 15:00:00"


@pytest.mark.asyncio
async def test_monday_1515_skips_due_to_cooldown(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))
    assert len(mock_wa.sent_messages) == 2

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 15, tzinfo=BOLIVIA_TZ))
    assert len(mock_wa.sent_messages) == 2  # sin nuevos envíos, todavía dentro del cooldown


@pytest.mark.asyncio
async def test_monday_1530_sends_again_after_interval(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))
    assert len(mock_wa.sent_messages) == 2

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 30, tzinfo=BOLIVIA_TZ))
    assert len(mock_wa.sent_messages) == 4


@pytest.mark.asyncio
async def test_monday_1800_escalates_instead_of_reminding(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 18, 0, tzinfo=BOLIVIA_TZ))

    # Un solo mensaje: la alerta consolidada al admin, no un recordatorio por supervisor.
    assert len(mock_wa.sent_messages) == 1
    assert "PLANIFICACIÓN PENDIENTE" in mock_wa.sent_messages[0]["text"]
    assert "Carlos Mendoza" in mock_wa.sent_messages[0]["text"]
    assert "Maria Suarez" in mock_wa.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_monday_1400_outside_window_sends_nothing(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 14, 0, tzinfo=BOLIVIA_TZ))

    assert len(mock_wa.sent_messages) == 0


@pytest.mark.asyncio
async def test_saturday_1144_sends_nothing(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 19, 11, 44, tzinfo=BOLIVIA_TZ))

    assert len(mock_wa.sent_messages) == 0


@pytest.mark.asyncio
async def test_saturday_1145_sends_single_notice(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 19, 11, 45, tzinfo=BOLIVIA_TZ))

    notices = [m for m in mock_wa.sent_messages if m["text"] == MSG_REMINDER_SATURDAY_NOTICE]
    assert len(notices) == 2  # ambos supervisores


@pytest.mark.asyncio
async def test_saturday_1200_does_not_duplicate(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 19, 11, 45, tzinfo=BOLIVIA_TZ))
    first_count = len(mock_wa.sent_messages)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 19, 12, 0, tzinfo=BOLIVIA_TZ))
    assert len(mock_wa.sent_messages) == first_count


@pytest.mark.asyncio
async def test_sunday_sends_nothing(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 20, 12, 0, tzinfo=BOLIVIA_TZ))

    assert len(mock_wa.sent_messages) == 0


@pytest.mark.asyncio
async def test_supervisor_with_active_planning_gets_no_reminder(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    # Lunes 15:00 -> fecha operativa martes 2026-09-15 (lunes por la tarde avanza al día siguiente).
    svc.sheets_repo.upsert("2026-09-15", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})

    await svc.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))

    assert len(mock_wa.sent_messages) == 1  # solo Maria Suarez (CBBA)
