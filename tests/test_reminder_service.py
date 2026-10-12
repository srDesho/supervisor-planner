"""
Unit tests for the per-day reminder/escalation schedule.

Calendar used: Monday 14/09/2026 ... Friday 18/09, Saturday 19/09,
Sunday 20/09. The schedule settings are pinned by conftest (pinned_schedule).
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.services.reminder_service import ReminderService
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.whatsapp.client import WhatsAppClient

SUPERVISORS = [
    {"Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Telefono": "70000002", "Nombre": "Maria Suarez", "Sede": "CBBA", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]

PENDING_REMINDER = "Aún no hemos recibido tu planificación"
ESCALATION_ALERT = "PLANIFICACIÓN PENDIENTE"


def _dt(day, hour, minute=0):
    """September 2026 datetime in Bolivia time."""
    return datetime(2026, 9, day, hour, minute, tzinfo=BOLIVIA_TZ)


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    return ReminderService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        supervisors_repo=SupervisorsRepository(client=fake_sheets)
    )


def _reminders(mock_wa):
    return [m for m in mock_wa.sent_messages if PENDING_REMINDER in m["text"]]


def _alerts(mock_wa):
    return [m for m in mock_wa.sent_messages if ESCALATION_ALERT in m["text"]]


# --- schedule table: (day, hour, minute) -> action, target date ---

REMINDER_CASES = [
    # Monday AM: catch-up, target = Monday itself
    ((14, 8, 0), "14/09/2026"),
    ((14, 9, 0), "14/09/2026"),
    ((14, 11, 0), "14/09/2026"),
    # Monday PM: target = Tuesday
    ((14, 15, 0), "15/09/2026"),
    ((14, 16, 0), "15/09/2026"),
    # Tuesday-Thursday PM: next day
    ((15, 16, 0), "16/09/2026"),
    ((16, 16, 0), "17/09/2026"),
    ((17, 16, 0), "18/09/2026"),
    # Friday PM: Saturday
    ((18, 16, 0), "19/09/2026"),
    # Saturday AM: target = Saturday itself
    ((19, 8, 0), "19/09/2026"),
    ((19, 10, 0), "19/09/2026"),
    ((19, 11, 30), "19/09/2026"),
]

ESCALATION_CASES = [
    # Monday after the AM cutoff: still for Monday
    ((14, 12, 0), "14/09/2026"),
    ((14, 13, 0), "14/09/2026"),
    ((14, 14, 30), "14/09/2026"),
    # Monday after the PM cutoff: Tuesday
    ((14, 18, 0), "15/09/2026"),
    ((14, 19, 0), "15/09/2026"),
    # Tuesday-Friday after the cutoff
    ((15, 18, 0), "16/09/2026"),
    ((16, 19, 0), "17/09/2026"),
    ((17, 18, 30), "18/09/2026"),
    ((18, 18, 0), "19/09/2026"),
]

NO_ACTION_CASES = [
    (14, 7, 59),   # Monday before the AM window
    (15, 10, 0),   # Tuesday morning
    (16, 14, 59),  # Wednesday just before the PM window
    (19, 7, 59),   # Saturday before the AM window
    (19, 11, 31),  # Saturday after the last reminder
    (19, 12, 0),   # Saturday noon (machine off in reality)
    (19, 16, 0),   # Saturday PM
    (20, 10, 0),   # Sunday AM
    (20, 16, 0),   # Sunday PM
]


@pytest.mark.asyncio
@pytest.mark.parametrize("when,target", REMINDER_CASES)
async def test_reminder_ticks_target_the_right_date(fake_sheets, when, target):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(*when))

    reminders = _reminders(mock_wa)
    assert len(reminders) == 2  # both supervisors
    assert all(target in m["text"] for m in reminders)
    assert _alerts(mock_wa) == []
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("when,target", ESCALATION_CASES)
async def test_escalation_ticks_flag_the_right_date(fake_sheets, when, target):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(*when))

    assert _reminders(mock_wa) == []
    alerts = _alerts(mock_wa)
    assert len(alerts) == 1
    assert f"Fecha de trabajo: {target}" in alerts[0]["text"]

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    day, month, year = target.split("/")
    assert len(rows) == 2
    assert all(r["Estado"] == "PENDIENTE_ESCALADO" for r in rows)
    assert all(r["Fecha_Trabajo"] == f"{year}-{month}-{day}" for r in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("when", NO_ACTION_CASES)
async def test_no_action_outside_schedule(fake_sheets, when):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(*when))

    assert mock_wa.sent_messages == []
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []


@pytest.mark.asyncio
async def test_saturday_never_escalates(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    for hour, minute in [(8, 0), (10, 0), (11, 30), (12, 0), (16, 0)]:
        await svc.run_reminder_cycle(eval_time=_dt(19, hour, minute))

    assert _alerts(mock_wa) == []
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []


# --- cooldown ---

@pytest.mark.asyncio
async def test_cooldown_blocks_reminder_within_the_hour(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))
    assert len(_reminders(mock_wa)) == 2
    row = svc.supervisors_repo.find_by_phone("70000001")
    assert row["Ultimo_Recordatorio"] == "2026-09-14 15:00:00"

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 30))
    assert len(_reminders(mock_wa)) == 2  # still inside the 60-min cooldown

    await svc.run_reminder_cycle(eval_time=_dt(14, 16, 0))
    assert len(_reminders(mock_wa)) == 4  # cooldown elapsed


@pytest.mark.asyncio
async def test_cooldown_is_configurable(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.settings.REMINDER_COOLDOWN_MINUTES = 1  # restored by monkeypatch in conftest

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))
    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 1))

    assert len(_reminders(mock_wa)) == 4


@pytest.mark.asyncio
async def test_cooldown_applies_on_monday_am(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(14, 8, 0))
    await svc.run_reminder_cycle(eval_time=_dt(14, 8, 30))

    assert len(_reminders(mock_wa)) == 2


@pytest.mark.asyncio
async def test_saturday_last_reminder_ignores_cooldown(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(19, 11, 0))
    assert len(_reminders(mock_wa)) == 2

    await svc.run_reminder_cycle(eval_time=_dt(19, 11, 30))  # 30 min later, cooldown is 60
    assert len(_reminders(mock_wa)) == 4


@pytest.mark.asyncio
async def test_saturday_before_last_tick_still_respects_cooldown(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(19, 10, 0))
    await svc.run_reminder_cycle(eval_time=_dt(19, 10, 30))

    assert len(_reminders(mock_wa)) == 2


@pytest.mark.asyncio
async def test_last_reminder_tick_with_seconds_counts_as_1130(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(19, 11, 0))
    await svc.run_reminder_cycle(
        eval_time=datetime(2026, 9, 19, 11, 30, 0, 400000, tzinfo=BOLIVIA_TZ)
    )

    assert len(_reminders(mock_wa)) == 4


# --- who gets reminded ---

@pytest.mark.asyncio
async def test_registered_supervisor_is_not_reminded(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.sheets_repo.upsert("2026-09-15", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})

    await svc.run_reminder_cycle(eval_time=_dt(14, 16, 0))

    reminders = _reminders(mock_wa)
    assert [m["chat_id"] for m in reminders] == ["59170000002@c.us"]


@pytest.mark.asyncio
async def test_reminders_go_to_telefono_as_c_us_with_country_code(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    assert sorted(m["chat_id"] for m in mock_wa.sent_messages) == [
        "59170000001@c.us",
        "59170000002@c.us",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient,expected", [
    ("70000001", "59170000001@c.us"),
    (70000001, "59170000001@c.us"),
    ("+591 7000-0001", "59170000001@c.us"),
    ("59170000001", "59170000001@c.us"),
    ("88283556139076@lid", "88283556139076@lid"),
])
async def test_client_formats_recipient(recipient, expected):
    wa = WhatsAppClient()
    await wa.send_message(recipient, "hola")
    assert wa.sent_messages[-1]["chat_id"] == expected


# --- reminders vs live conversations (per-phone lock, state, recent activity) ---

import asyncio  # noqa: E402

from app.core import locks  # noqa: E402
from app.services.conversation_service import ConversationService  # noqa: E402
from app.whatsapp.templates import (  # noqa: E402
    MSG_REMINDER_AWAITING_CONFIRMATION,
    MSG_REMINDER_AWAITING_RUTA_CODE,
    MSG_REMINDER_AWAITING_SELECTION,
)


@pytest.fixture
def activity_clock(monkeypatch):
    class Clock:
        t = 5000.0

    monkeypatch.setattr(locks, "_now", lambda: Clock.t)
    return Clock


def _recipients(mock_wa):
    return sorted(m["chat_id"] for m in mock_wa.sent_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["AWAITING_CONFIRMATION", "AWAITING_SELECTION", "AWAITING_RUTA_CODE"])
async def test_no_reminder_while_in_an_active_state_and_just_wrote(fake_sheets, activity_clock, state):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    ConversationService().set("70000001", state, payload={})
    locks.touch_activity("70000001")

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    assert _recipients(mock_wa) == ["59170000002@c.us"]  # only the other supervisor


@pytest.mark.asyncio
async def test_no_reminder_if_the_supervisor_wrote_in_the_last_10_minutes(fake_sheets, activity_clock):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    locks.touch_activity("70000001")  # no pending state at all

    activity_clock.t += 9 * 60
    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))
    assert _recipients(mock_wa) == ["59170000002@c.us"]

    activity_clock.t += 2 * 60  # now 11 minutes since the supervisor wrote
    await svc.run_reminder_cycle(eval_time=_dt(14, 16, 0))
    assert "59170000001@c.us" in _recipients(mock_wa)


@pytest.mark.asyncio
async def test_activity_window_is_configurable(fake_sheets, activity_clock):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.settings.REMINDER_ACTIVITY_WINDOW_MINUTES = 1  # restored by conftest
    locks.touch_activity("70000001")
    activity_clock.t += 90

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    assert _recipients(mock_wa) == ["59170000001@c.us", "59170000002@c.us"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state,expected", [
    ("AWAITING_CONFIRMATION", MSG_REMINDER_AWAITING_CONFIRMATION),
    ("AWAITING_SELECTION", MSG_REMINDER_AWAITING_SELECTION),
    ("AWAITING_RUTA_CODE", MSG_REMINDER_AWAITING_RUTA_CODE),
])
async def test_abandoned_state_gets_its_own_reminder_text(fake_sheets, activity_clock, state, expected):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    ConversationService().set("70000001", state, payload={})
    locks.touch_activity("70000001")
    activity_clock.t += 15 * 60  # wrote 15 min ago and left: not a live conversation any more

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    texts = {m["chat_id"]: m["text"] for m in mock_wa.sent_messages}
    assert texts["59170000001@c.us"] == expected
    assert "Aún no hemos recibido" in texts["59170000002@c.us"]  # no state: the generic text


@pytest.mark.asyncio
async def test_reminder_waits_for_the_supervisors_lock(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    events = []

    original_send = mock_wa.send_message

    async def recording_send(chat_id, text):
        events.append(f"reminder to {chat_id}")
        return await original_send(chat_id, text)

    mock_wa.send_message = recording_send

    async def handler_holding_the_lock():
        async with locks.phone_lock("70000001"):
            events.append("handler start")
            await asyncio.sleep(0.15)
            events.append("handler end")

    holder = asyncio.create_task(handler_holding_the_lock())
    await asyncio.sleep(0.02)
    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))
    await holder

    assert events.index("handler end") < events.index("reminder to 70000001")


# --- Sheets cost of a reminder tick ---

from collections import Counter  # noqa: E402


def _five_supervisors(last_reminder=""):
    return [
        {"Telefono": f"7000000{i}", "Nombre": f"Sup {i}", "Sede": "SCZ", "Zona": "N",
         "Activo": "TRUE", "Ultimo_Recordatorio": last_reminder}
        for i in range(1, 6)
    ]


def _service_with(fake_sheets, mock_wa, supervisors):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, supervisors)
    reads = Counter()
    original = fake_sheets.get_all_records

    def counting(name):
        reads[name] += 1
        return original(name)

    fake_sheets.get_all_records = counting
    fake_sheets.batch_calls = 0
    return (
        ReminderService(
            whatsapp_client=mock_wa,
            sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
            supervisors_repo=SupervisorsRepository(client=fake_sheets),
        ),
        reads,
    )


@pytest.mark.asyncio
async def test_a_tick_reads_planificacion_diaria_exactly_once(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors())

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    assert len(_reminders(mock_wa)) == 5
    assert reads["PLANIFICACION_DIARIA"] == 1          # not 5 (one per supervisor)
    assert reads["SUPERVISORES"] <= 2                  # cache + one read to locate rows
    assert fake_sheets.batch_calls == 1                # one write for all five
    stamps = [r["Ultimo_Recordatorio"] for r in fake_sheets.get_all_records("SUPERVISORES")]
    assert stamps == ["2026-09-14 15:00:00"] * 5


@pytest.mark.asyncio
async def test_everyone_in_cooldown_means_no_sheet_reads_or_writes_for_planning(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors("2026-09-14 14:45:00"))

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))  # 15 min after the last reminder, cooldown is 60

    assert mock_wa.sent_messages == []
    assert reads["PLANIFICACION_DIARIA"] == 0
    assert fake_sheets.batch_calls == 0


@pytest.mark.asyncio
async def test_second_tick_inside_the_cooldown_does_not_read_planning_again(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors())

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))
    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 30))

    assert len(_reminders(mock_wa)) == 5
    assert reads["PLANIFICACION_DIARIA"] == 1  # the second tick stopped at the cooldown
    assert fake_sheets.batch_calls == 1


@pytest.mark.asyncio
async def test_only_supervisors_actually_reminded_are_written(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors())
    svc.sheets_repo.upsert("2026-09-15", "SCZ", "Sup 2", {"Modalidad": "OFICINA"})  # Sup 2 already planned
    ConversationService().set("70000004", "AWAITING_CONFIRMATION", payload={})
    locks.touch_activity("70000004")                                                  # Sup 4 is mid-conversation

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    stamps = {r["Nombre"]: r["Ultimo_Recordatorio"] for r in fake_sheets.get_all_records("SUPERVISORES")}
    assert stamps == {
        "Sup 1": "2026-09-14 15:00:00",
        "Sup 2": "",
        "Sup 3": "2026-09-14 15:00:00",
        "Sup 4": "",
        "Sup 5": "2026-09-14 15:00:00",
    }


@pytest.mark.asyncio
async def test_no_write_at_all_if_nobody_was_reminded(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors())
    for i in range(1, 6):
        svc.sheets_repo.upsert("2026-09-15", "SCZ", f"Sup {i}", {"Modalidad": "OFICINA"})

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    assert mock_wa.sent_messages == []
    assert fake_sheets.batch_calls == 0


@pytest.mark.asyncio
async def test_unreadable_planning_sheet_aborts_the_tick_without_reminding_anyone(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors())
    original = fake_sheets.get_all_records

    def failing(name):
        if name == "PLANIFICACION_DIARIA":
            raise RuntimeError("429 after retries")
        return original(name)

    fake_sheets.get_all_records = failing

    await svc.run_reminder_cycle(eval_time=_dt(14, 15, 0))

    assert mock_wa.sent_messages == []


@pytest.mark.asyncio
async def test_escalation_reads_once_per_tick_and_writes_nothing_when_all_are_flagged(fake_sheets):
    mock_wa = WhatsAppClient()
    svc, reads = _service_with(fake_sheets, mock_wa, _five_supervisors())

    await svc.run_reminder_cycle(eval_time=_dt(14, 18, 0))
    first_tick_reads = reads["PLANIFICACION_DIARIA"]
    assert first_tick_reads == 1 + 5  # 1 index read + 1 re-check before each of the 5 flag rows

    await svc.run_reminder_cycle(eval_time=_dt(14, 18, 30))

    assert reads["PLANIFICACION_DIARIA"] == first_tick_reads + 1  # later ticks: a single read
    flagged = [r for r in fake_sheets._rows["PLANIFICACION_DIARIA"]]
    assert len(flagged) == 5
    assert len(_alerts(mock_wa)) == 1
