"""
Unit tests for the scheduler: clock-aligned cron ticks and the startup check
(skipped when the next tick is <= 30 seconds away).
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.services import scheduler_service
from app.services.scheduler_service import (
    build_cron_trigger,
    decide_startup_check,
    schedule_startup_check,
)


def _at(hour, minute, second=0):
    return datetime(2026, 9, 14, hour, minute, second, tzinfo=BOLIVIA_TZ)  # Lunes


def _trigger(interval=30):
    return build_cron_trigger(interval, "America/La_Paz")


@pytest.mark.parametrize("interval,now,expected_next", [
    (30, _at(8, 7), (8, 30)),
    (30, _at(8, 30), (8, 30)),
    (30, _at(8, 31), (9, 0)),
    (60, _at(8, 7), (9, 0)),
    (1, _at(8, 7, 20), (8, 8)),
])
def test_cron_ticks_are_aligned_to_the_clock(interval, now, expected_next):
    next_tick = _trigger(interval).get_next_fire_time(None, now)
    assert (next_tick.hour, next_tick.minute, next_tick.second) == (*expected_next, 0)


@pytest.mark.parametrize("interval", [0, 7, 25, 90, -5])
def test_interval_must_divide_60(interval):
    with pytest.raises(ValueError):
        build_cron_trigger(interval, "America/La_Paz")


def test_startup_at_0829_50_is_skipped_tick_in_10s():
    should_run, seconds = decide_startup_check(_trigger(), _at(8, 29, 50))
    assert should_run is False
    assert seconds == 10


def test_startup_at_0829_00_runs_tick_in_60s():
    should_run, seconds = decide_startup_check(_trigger(), _at(8, 29, 0))
    assert should_run is True
    assert seconds == 60


@pytest.mark.parametrize("now,should_run", [
    (_at(8, 29, 30), False),  # exactly 30s -> still skipped (<= 30)
    (_at(8, 29, 29), True),   # 31s -> runs
    (_at(8, 30, 0), False),   # exactly on the tick
    (_at(8, 7, 0), True),     # laptop booted 7 minutes late
])
def test_startup_threshold_boundaries(now, should_run):
    assert decide_startup_check(_trigger(), now)[0] is should_run


@pytest.fixture
def queued_jobs(monkeypatch):
    jobs = []
    monkeypatch.setattr(scheduler_service.scheduler, "add_job", lambda *a, **kw: jobs.append((a, kw)))
    return jobs


def test_startup_check_not_queued_when_tick_is_imminent(queued_jobs):
    assert schedule_startup_check(_trigger(), _at(8, 29, 50)) is False
    assert queued_jobs == []


def test_startup_check_queued_once_when_tick_is_far(queued_jobs):
    assert schedule_startup_check(_trigger(), _at(8, 29, 0)) is True
    assert len(queued_jobs) == 1
    args, kwargs = queued_jobs[0]
    assert args[0] is scheduler_service._startup_check_job
    assert "trigger" not in kwargs  # no trigger -> runs once, immediately
    assert kwargs["misfire_grace_time"] == 60
