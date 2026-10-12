"""
Tests for the inbound message handler: FIFO lock per phone, duplicate
suppression, fallback reply on errors, idempotency after success, and logs.
The planning service is replaced by a stub: these tests are about orchestration.
"""
import asyncio
import logging

import pytest

from app.core import locks
from app.whatsapp import handlers, idempotency
from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp.templates import MSG_PROCESSING_ERROR

SUPERVISOR_PHONE = "70000001"
OTHER_PHONE = "70000002"
STRANGER_PHONE = "79999999"


def _msg(body, message_id="m1", phone=SUPERVISOR_PHONE):
    return ParsedWhatsAppMessage(
        event="message", session="default", message_id=message_id,
        from_phone=f"591{phone}", from_full=f"591{phone}@c.us", body=body,
    )


class _StubSupervisorService:
    AUTHORIZED = {SUPERVISOR_PHONE, OTHER_PHONE}

    def authenticate(self, phone):
        return {"Nombre": "Carlos", "Sede": "SCZ"} if phone in self.AUTHORIZED else None


class _StubWhatsApp:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return True


class StubPlanning:
    """Records start/end of every message; behavior per body: 'slow' sleeps, 'boom' raises."""

    def __init__(self):
        self.events = []
        self.supervisor_svc = _StubSupervisorService()
        self.whatsapp_client = _StubWhatsApp()
        self.calls = 0

    async def handle_message(self, msg):
        self.calls += 1
        self.events.append(f"start {msg.body}")
        if msg.body.startswith("slow"):
            await asyncio.sleep(0.1)
        if msg.body == "boom":
            raise RuntimeError("Sheets exploded")
        await asyncio.sleep(0)
        self.events.append(f"end {msg.body}")


@pytest.fixture
def planning(monkeypatch):
    stub = StubPlanning()
    monkeypatch.setattr(handlers, "get_planning_service", lambda: stub)
    return stub


@pytest.fixture
def clock(monkeypatch):
    """A controllable clock for the duplicate window."""
    class Clock:
        t = 1000.0

    monkeypatch.setattr(handlers, "_now", lambda: Clock.t)
    return Clock


# --- 1B.1 FIFO lock per phone ---

@pytest.mark.asyncio
async def test_same_phone_messages_are_processed_in_order_without_interleaving(planning):
    first = asyncio.create_task(handlers.handle_whatsapp_event(_msg("slow one", "m1")))
    second = asyncio.create_task(handlers.handle_whatsapp_event(_msg("quick two", "m2")))
    await asyncio.gather(first, second)

    assert planning.events == ["start slow one", "end slow one", "start quick two", "end quick two"]


@pytest.mark.asyncio
async def test_replies_come_out_in_arrival_order(planning):
    tasks = [
        asyncio.create_task(handlers.handle_whatsapp_event(_msg(f"slow {i}", f"m{i}")))
        for i in range(3)
    ]
    await asyncio.gather(*tasks)

    assert [e for e in planning.events if e.startswith("end")] == ["end slow 0", "end slow 1", "end slow 2"]
    assert planning.events == [
        "start slow 0", "end slow 0", "start slow 1", "end slow 1", "start slow 2", "end slow 2",
    ]


@pytest.mark.asyncio
async def test_different_phones_do_not_wait_for_each_other(planning):
    slow = asyncio.create_task(handlers.handle_whatsapp_event(_msg("slow a", "m1", SUPERVISOR_PHONE)))
    await asyncio.sleep(0.01)
    await handlers.handle_whatsapp_event(_msg("quick b", "m2", OTHER_PHONE))

    assert not slow.done()  # the other supervisor was served while the first was still busy
    await slow
    assert planning.events == ["start slow a", "start quick b", "end quick b", "end slow a"]


@pytest.mark.asyncio
async def test_locks_are_cleaned_up(planning):
    task_a = asyncio.create_task(handlers.handle_whatsapp_event(_msg("slow a", "m1")))
    task_b = asyncio.create_task(handlers.handle_whatsapp_event(_msg("slow b", "m2")))
    await asyncio.sleep(0.02)
    assert locks.active_lock_count() == 1  # one phone: holder + waiter share one entry
    await asyncio.gather(task_a, task_b)
    assert locks.active_lock_count() == 0

    await handlers.handle_whatsapp_event(_msg("boom", "m3"))  # also after an error
    assert locks.active_lock_count() == 0

    for i in range(20):  # many different phones leave nothing behind
        await handlers.handle_whatsapp_event(_msg(f"hi {i}", f"x{i}", f"7100{i:04d}"))
    assert locks.active_lock_count() == 0


@pytest.mark.asyncio
async def test_retry_of_a_message_still_being_processed_is_not_run_twice(planning, monkeypatch):
    monkeypatch.setattr(handlers.get_settings(), "DUPLICATE_MESSAGE_WINDOW_SECONDS", 0)

    first = asyncio.create_task(handlers.handle_whatsapp_event(_msg("slow x", "same-id")))
    retry = asyncio.create_task(handlers.handle_whatsapp_event(_msg("slow x", "same-id")))
    results = await asyncio.gather(first, retry)

    assert planning.calls == 1
    assert results == [True, False]


# --- 1B.2 duplicate suppression ---

@pytest.mark.asyncio
async def test_same_text_within_two_seconds_is_ignored(planning, clock):
    assert await handlers.handle_whatsapp_event(_msg("3809", "m1")) is True
    clock.t += 1.0
    assert await handlers.handle_whatsapp_event(_msg("3809", "m2")) is False

    assert planning.calls == 1


@pytest.mark.asyncio
async def test_same_text_after_more_than_three_seconds_is_processed_twice(planning, clock):
    await handlers.handle_whatsapp_event(_msg("3809", "m1"))
    clock.t += 3.5
    await handlers.handle_whatsapp_event(_msg("3809", "m2"))

    assert planning.calls == 2


@pytest.mark.asyncio
async def test_duplicates_are_compared_after_normalization(planning, clock):
    await handlers.handle_whatsapp_event(_msg("Oficína", "m1"))
    clock.t += 0.5
    await handlers.handle_whatsapp_event(_msg("  oficina ", "m2"))

    assert planning.calls == 1


@pytest.mark.asyncio
async def test_different_text_or_different_phone_is_not_a_duplicate(planning, clock):
    await handlers.handle_whatsapp_event(_msg("3809", "m1"))
    clock.t += 0.5
    await handlers.handle_whatsapp_event(_msg("3808", "m2"))
    await handlers.handle_whatsapp_event(_msg("3808", "m3", OTHER_PHONE))

    assert planning.calls == 3


@pytest.mark.asyncio
async def test_the_window_slides_with_every_message(planning, clock):
    await handlers.handle_whatsapp_event(_msg("ok", "m1"))
    clock.t += 1.5
    await handlers.handle_whatsapp_event(_msg("ok", "m2"))   # suppressed, timestamp refreshed
    clock.t += 1.5
    await handlers.handle_whatsapp_event(_msg("ok", "m3"))   # 1.5 s after the last one: suppressed

    assert planning.calls == 1


@pytest.mark.asyncio
async def test_suppression_is_logged(planning, clock, caplog):
    caplog.set_level(logging.INFO, logger="app.whatsapp.handlers")
    await handlers.handle_whatsapp_event(_msg("3809", "m1"))
    await handlers.handle_whatsapp_event(_msg("3809", "m2"))

    assert f"Suppressed duplicate message from {SUPERVISOR_PHONE} id=m2" in caplog.text


# --- 1B.4 fallback reply, idempotency after success ---

@pytest.mark.asyncio
async def test_error_sends_fallback_and_message_is_not_marked_processed(planning):
    result = await handlers.handle_whatsapp_event(_msg("boom", "m-fail"))

    assert result is False
    assert planning.whatsapp_client.sent == [(f"591{SUPERVISOR_PHONE}@c.us", MSG_PROCESSING_ERROR)]
    assert idempotency.is_processed("m-fail") is False


@pytest.mark.asyncio
async def test_failed_message_can_be_retried_and_then_is_marked(planning):
    await handlers.handle_whatsapp_event(_msg("boom", "m1"))
    planning_ok = _msg("fine", "m1")  # WAHA retries the same message id

    assert await handlers.handle_whatsapp_event(planning_ok) is True
    assert idempotency.is_processed("m1") is True
    assert await handlers.handle_whatsapp_event(planning_ok) is False  # now it is a real duplicate


@pytest.mark.asyncio
async def test_resending_the_same_text_right_after_a_failure_is_not_suppressed(planning, clock):
    await handlers.handle_whatsapp_event(_msg("boom", "m1"))
    clock.t += 0.5
    await handlers.handle_whatsapp_event(_msg("boom", "m2"))

    assert planning.calls == 2


@pytest.mark.asyncio
async def test_unknown_sender_gets_no_fallback_reply(planning):
    result = await handlers.handle_whatsapp_event(_msg("boom", "m1", STRANGER_PHONE))

    assert result is False
    assert planning.whatsapp_client.sent == []


@pytest.mark.asyncio
async def test_failure_of_the_fallback_itself_does_not_raise(planning):
    async def broken_send(chat_id, text):
        raise RuntimeError("WAHA down")

    planning.whatsapp_client.send_message = broken_send

    assert await handlers.handle_whatsapp_event(_msg("boom", "m1")) is False


@pytest.mark.asyncio
async def test_message_is_marked_processed_only_after_success(planning):
    seen_during = []
    original = planning.handle_message

    async def spy(msg):
        seen_during.append(idempotency.is_processed(msg.message_id))
        await original(msg)

    planning.handle_message = spy
    await handlers.handle_whatsapp_event(_msg("hello", "m1"))

    assert seen_during == [False]          # not marked while processing
    assert idempotency.is_processed("m1")  # marked once it finished


# --- 1B.5 logs ---

@pytest.mark.asyncio
async def test_processing_and_finished_logs(planning, caplog):
    caplog.set_level(logging.INFO, logger="app.whatsapp.handlers")

    await handlers.handle_whatsapp_event(_msg("hello", "m1"))

    assert f"Processing message from {SUPERVISOR_PHONE} id=m1" in caplog.text
    finished = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Finished message")]
    assert len(finished) == 1
    assert finished[0].startswith(f"Finished message from {SUPERVISOR_PHONE} id=m1 in ")
    assert finished[0].endswith("s")


@pytest.mark.asyncio
async def test_failed_log_has_the_error_and_the_traceback(planning, caplog):
    caplog.set_level(logging.INFO, logger="app.whatsapp.handlers")

    await handlers.handle_whatsapp_event(_msg("boom", "m1"))

    failed = [r for r in caplog.records if r.getMessage().startswith("Failed message")]
    assert len(failed) == 1
    assert f"Failed message from {SUPERVISOR_PHONE} id=m1 in " in failed[0].getMessage()
    assert "Sheets exploded" in failed[0].getMessage()
    assert failed[0].exc_info is not None  # full stack trace


@pytest.mark.asyncio
async def test_final_punctuation_does_not_make_a_text_different_for_the_duplicate_filter(planning, clock):
    await handlers.handle_whatsapp_event(_msg("ok", "m1"))
    clock.t += 0.5
    assert await handlers.handle_whatsapp_event(_msg("ok.", "m2")) is False   # "ok" == "ok."
    clock.t += 0.5
    assert await handlers.handle_whatsapp_event(_msg("  OK!  ", "m3")) is False

    assert planning.calls == 1
