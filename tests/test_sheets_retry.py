"""
Tests for retries with exponential backoff in GoogleSheetsClient:
429 and 5xx are retried (3 times: 1s, 2s, 4s), permanent errors are not.
"""
import logging

import pytest
from gspread.exceptions import APIError

from app.sheets import client as client_module
from app.sheets.client import GoogleSheetsClient, GoogleSheetsError


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = f"error {status_code}"

    def json(self):
        return {"error": {"code": self.status_code, "message": f"HTTP {self.status_code}", "status": "ERR"}}


def api_error(status_code):
    return APIError(FakeResponse(status_code))


class FakeWorksheet:
    """Each method pops the next scripted outcome: an exception to raise or a value to return."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def _next(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get_all_records(self):
        return self._next()

    def append_row(self, row):
        return self._next()

    def update(self, cell_range, values):
        return self._next()

    def batch_update(self, data, **kwargs):
        return self._next()


class FakeSpreadsheet:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, name):
        return self.ws


def make_client(ws):
    """A GoogleSheetsClient wired to a fake worksheet, without touching credentials or the network."""
    client = object.__new__(GoogleSheetsClient)
    client.is_connected = True
    client.credentials_path = "unused"
    client.spreadsheet_id = "unused"
    client._spreadsheet = FakeSpreadsheet(ws)
    client._worksheets = {}
    return client


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(client_module, "_sleep", recorded.append)
    return recorded


ROWS = [{"Nombre": "Carlos"}]


def test_success_on_first_try_does_not_wait(sleeps):
    ws = FakeWorksheet([ROWS])

    assert make_client(ws).get_all_records("S") == ROWS
    assert ws.calls == 1 and sleeps == []


def test_429_is_retried_three_times_with_growing_delays_and_the_fourth_attempt_wins(sleeps):
    ws = FakeWorksheet([api_error(429), api_error(429), api_error(429), ROWS])

    assert make_client(ws).get_all_records("S") == ROWS

    assert ws.calls == 4
    assert sleeps == [1, 2, 4]


def test_after_three_failed_retries_the_error_propagates(sleeps):
    ws = FakeWorksheet([api_error(429)] * 4 + [ROWS])

    with pytest.raises(GoogleSheetsError):
        make_client(ws).get_all_records("S")

    assert ws.calls == 4          # 1 attempt + 3 retries, never a 5th
    assert sleeps == [1, 2, 4]


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_retried(sleeps, status):
    ws = FakeWorksheet([api_error(status), ROWS])

    assert make_client(ws).get_all_records("S") == ROWS
    assert ws.calls == 2 and sleeps == [1]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_errors_are_not_retried(sleeps, status):
    ws = FakeWorksheet([api_error(status), ROWS])

    with pytest.raises(GoogleSheetsError):
        make_client(ws).get_all_records("S")

    assert ws.calls == 1
    assert sleeps == []


def test_404_is_not_retried_on_writes_either(sleeps):
    ws = FakeWorksheet([api_error(404), None])

    with pytest.raises(GoogleSheetsError):
        make_client(ws).append_row("S", ["x"])

    assert ws.calls == 1 and sleeps == []


@pytest.mark.parametrize("operation", [
    lambda c: c.append_row("S", ["x"]),
    lambda c: c.update_row("S", 2, ["x"]),
    lambda c: c.batch_update_cells("S", [{"range": "F2", "values": [["t"]]}]),
])
def test_writes_are_retried_too(sleeps, operation):
    ws = FakeWorksheet([api_error(429), None])

    operation(make_client(ws))

    assert ws.calls == 2 and sleeps == [1]


def test_retry_settings_are_configurable(sleeps, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "SHEETS_MAX_RETRIES", 1)
    monkeypatch.setattr(get_settings(), "SHEETS_RETRY_BASE_DELAY", 0.5)
    ws = FakeWorksheet([api_error(429), api_error(429), ROWS])

    with pytest.raises(GoogleSheetsError):
        make_client(ws).get_all_records("S")

    assert ws.calls == 2 and sleeps == [0.5]


def test_each_retry_is_logged(sleeps, caplog):
    caplog.set_level(logging.WARNING, logger="app.sheets.client")
    ws = FakeWorksheet([api_error(429), api_error(429), ROWS])

    make_client(ws).get_all_records("SUPERVISORES")

    assert "Retry 1/3 for get_all_records(SUPERVISORES) after 429, waiting 1s" in caplog.text
    assert "Retry 2/3 for get_all_records(SUPERVISORES) after 429, waiting 2s" in caplog.text


def test_batch_update_with_nothing_to_write_makes_no_request(sleeps):
    ws = FakeWorksheet([])

    make_client(ws).batch_update_cells("S", [])

    assert ws.calls == 0
