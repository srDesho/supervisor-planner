"""
Tests for the process-wide singletons and for run_in_sheets_thread
(all Sheets I/O on one dedicated thread, never on the event loop).
"""
import asyncio
import threading
import time
from datetime import datetime

import pytest

from app.business.dates import BOLIVIA_TZ
from app.core import singletons
from app.core.singletons import (
    get_audit_repo,
    get_masters_service,
    get_planning_repo,
    get_planning_service,
    get_reminder_service,
    get_sheets_client,
    get_sheets_executor,
    get_supervisor_service,
    get_supervisors_repo,
    init_singletons,
    reset_singletons,
)
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.sheets.client import GoogleSheetsError, run_in_sheets_thread
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.parser import ParsedWhatsAppMessage


@pytest.fixture(autouse=True)
def clean_singletons():
    reset_singletons()
    yield
    reset_singletons()


# --- (a) singletons: same reference every time ---

def test_getters_return_the_same_instance(fake_sheets):
    init_singletons(client=fake_sheets)

    getters = [
        get_sheets_client, get_sheets_executor, get_masters_service, get_supervisors_repo,
        get_planning_repo, get_audit_repo, get_supervisor_service, get_planning_service,
        get_reminder_service,
    ]
    for getter in getters:
        assert getter() is getter(), getter.__name__


def test_init_is_idempotent(fake_sheets):
    init_singletons(client=fake_sheets)
    first = (get_planning_service(), get_supervisors_repo(), get_sheets_executor())

    init_singletons()

    assert (get_planning_service(), get_supervisors_repo(), get_sheets_executor()) == first


def test_one_sheets_client_is_shared_by_every_repository(fake_sheets):
    init_singletons(client=fake_sheets)

    assert get_sheets_client() is fake_sheets
    assert get_supervisors_repo().client is fake_sheets
    assert get_planning_repo().client is fake_sheets
    assert get_audit_repo().client is fake_sheets
    assert get_masters_service()._client is fake_sheets


def test_services_share_the_same_repositories_and_caches(fake_sheets):
    init_singletons(client=fake_sheets)
    planning = get_planning_service()
    reminders = get_reminder_service()

    assert planning.sheets_repo is get_planning_repo() is reminders.sheets_repo
    assert planning.masters_service is get_masters_service()
    assert planning.supervisor_svc is get_supervisor_service()
    assert planning.supervisor_svc.repo is get_supervisors_repo() is reminders.supervisors_repo
    assert planning.whatsapp_client is reminders.whatsapp_client


def test_services_built_without_arguments_use_the_singletons(fake_sheets):
    init_singletons(client=fake_sheets)

    assert PlanningService().sheets_repo is get_planning_repo()
    assert PlanningService().masters_service is get_masters_service()
    assert SupervisorService().repo is get_supervisors_repo()
    assert AuditService().repo is get_audit_repo()
    assert SupervisorsRepository().client is fake_sheets
    assert GoogleSheetsPlanningRepository().client is fake_sheets
    assert AuditRepository().client is fake_sheets


def test_reset_builds_new_instances(fake_sheets):
    init_singletons(client=fake_sheets)
    old = get_planning_service()

    reset_singletons()
    init_singletons(client=fake_sheets)

    assert get_planning_service() is not old


def test_startup_fails_if_the_sheets_client_cannot_connect(monkeypatch):
    class DisconnectedClient:
        is_connected = False

    monkeypatch.setattr(singletons, "GoogleSheetsClient", DisconnectedClient)

    with pytest.raises(GoogleSheetsError):
        init_singletons()


def test_whatsapp_client_keeps_a_bounded_history():
    import asyncio as _asyncio

    wa = WhatsAppClient()
    wa.MAX_SENT_MESSAGES_KEPT = 5

    async def send_many():
        for i in range(12):
            await wa.send_message("70000001", f"m{i}")

    _asyncio.run(send_many())

    assert [m["text"] for m in wa.sent_messages] == [f"m{i}" for i in range(7, 12)]


# --- (b) run_in_sheets_thread: does not block the event loop ---

@pytest.mark.asyncio
async def test_run_in_sheets_thread_does_not_block_the_event_loop():
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    def slow_sheet_call():
        time.sleep(0.3)  # stands in for a blocking gspread request
        return threading.current_thread().name

    ticker_task = asyncio.create_task(ticker())
    await asyncio.gather(run_in_sheets_thread(slow_sheet_call), run_in_sheets_thread(slow_sheet_call))
    ticker_task.cancel()

    # ~0.6 s of blocking calls: a blocked loop would have produced ~0 ticks.
    assert ticks >= 15


@pytest.mark.asyncio
async def test_sheets_calls_run_on_one_dedicated_thread_one_at_a_time():
    spans = []

    def sheet_call(tag):
        start = time.monotonic()
        time.sleep(0.1)
        spans.append((tag, start, time.monotonic(), threading.current_thread().name))

    await asyncio.gather(*(run_in_sheets_thread(sheet_call, i) for i in range(3)))

    assert len(spans) == 3
    assert {name for *_, name in spans} == {spans[0][3]}      # always the same thread...
    assert spans[0][3].startswith("sheets")                  # ...the dedicated one
    assert threading.current_thread().name != spans[0][3]    # ...not the event loop thread
    spans.sort(key=lambda s: s[1])
    for (_, _, end, _), (_, next_start, _, _) in zip(spans, spans[1:]):
        assert next_start >= end - 0.005                     # serialized: no overlap


@pytest.mark.asyncio
async def test_run_in_sheets_thread_passes_arguments_and_propagates_errors():
    assert await run_in_sheets_thread(lambda a, b=0: a + b, 1, b=2) == 3

    def boom():
        raise GoogleSheetsError("429")

    with pytest.raises(GoogleSheetsError):
        await run_in_sheets_thread(boom)


@pytest.mark.asyncio
async def test_a_slow_sheet_does_not_freeze_the_event_loop_during_a_message(fake_sheets):
    """End to end: PlanningService.handle_message with a 0.3 s-per-read Sheet keeps the loop alive."""
    original = fake_sheets.get_all_records

    def slow_get_all_records(name):
        time.sleep(0.3)
        return original(name)

    fake_sheets.get_all_records = slow_get_all_records
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, [
        {"Nombre": "Carlos Mendoza", "Telefono": "70000001", "Sede": "SCZ", "Zona": "N",
         "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    ])
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()
    mock_wa = WhatsAppClient()
    svc = PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets)),
    )

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    msg = ParsedWhatsAppMessage(event="message", session="default", message_id="m1",
                                from_phone="70000001", body="oficina")
    ticker_task = asyncio.create_task(ticker())
    await svc.handle_message(msg, eval_datetime=datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ))
    ticker_task.cancel()

    assert "CONFIRMA TU PLANIFICACIÓN" in mock_wa.sent_messages[-1]["text"]
    assert ticks >= 15  # several 0.3 s reads happened, none of them on the loop
