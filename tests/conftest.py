"""
Shared Pytest fixtures.

There is no local database anymore: all persistence lives in Google Sheets.
`fake_sheets` provides an in-memory stand-in for GoogleSheetsClient (the
subset of its API the repositories actually use: get_all_records,
append_row, update_row), so repository/service tests never touch real
credentials or the network.
"""
from typing import Any, Dict, List, Optional

import pytest
from starlette.testclient import TestClient

from app.main import app


class FakeGoogleSheetsClient:
    """In-memory stand-in for app.sheets.client.GoogleSheetsClient."""

    def __init__(self):
        self.is_connected = True
        self._headers: Dict[str, List[str]] = {}
        self._rows: Dict[str, List[List[Any]]] = {}
        self._created_sheets: List[str] = []

    def set_headers(self, name: str, headers: List[str]) -> None:
        self._headers[name] = list(headers)
        self._rows.setdefault(name, [])

    def seed_records(self, name: str, headers: List[str], records: List[Dict[str, Any]]) -> None:
        """Seeds a worksheet with a header row and a list of dict records."""
        self.set_headers(name, headers)
        self._rows[name] = [[rec.get(h, "") for h in headers] for rec in records]

    def get_all_records(self, name: str) -> List[Dict[str, Any]]:
        headers = self._headers.get(name, [])
        return [dict(zip(headers, row)) for row in self._rows.get(name, [])]

    def append_row(self, name: str, row: List[Any]) -> None:
        self._rows.setdefault(name, []).append(list(row))

    def update_row(self, name: str, row_index: int, row: List[Any]) -> None:
        # row_index is 1-based including the header row (row 1 = headers).
        idx = row_index - 2
        rows = self._rows.setdefault(name, [])
        if 0 <= idx < len(rows):
            rows[idx] = list(row)
        else:
            raise IndexError(f"No row at sheet index {row_index} in '{name}'")

    def batch_update_cells(self, name: str, updates: List[Dict[str, Any]]) -> None:
        """Mirror of GoogleSheetsClient.batch_update_cells for single-cell A1 ranges like 'F5'."""
        if not updates:  # like the real client: nothing to write, no request
            return
        self.batch_calls = getattr(self, "batch_calls", 0) + 1
        for update in updates:
            a1 = update["range"]
            col = ord(a1[0]) - ord("A")
            row_index = int(a1[1:])
            self._rows[name][row_index - 2][col] = update["values"][0][0]

    def worksheet_exists(self, name: str) -> bool:
        return name in self._headers

    def create_worksheet(self, name: str, headers: List[str], rows: int = 1000) -> None:
        self.set_headers(name, headers)
        self._created_sheets.append(name)

    def ensure_worksheet(self, name: str, headers: List[str]) -> bool:
        if self.worksheet_exists(name):
            return True
        self.create_worksheet(name, headers)
        return False


@pytest.fixture
def fake_sheets() -> FakeGoogleSheetsClient:
    """A fresh in-memory Google Sheets stand-in for each test."""
    return FakeGoogleSheetsClient()


@pytest.fixture
def client(monkeypatch):
    """
    FastAPI TestClient. The lifespan's real startup work (building the Sheets
    singletons, Sheets warm-up, APScheduler with its startup-check cycle) is
    stubbed out: tests must never need credentials or touch the real Sheet.
    """
    import app.main as main_module

    async def _no_startup_checks():
        return None

    monkeypatch.setattr(main_module, "init_singletons", lambda: None)
    monkeypatch.setattr(main_module, "_startup_sheet_checks", _no_startup_checks)
    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "shutdown_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "shutdown_singletons", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def pinned_schedule(monkeypatch):
    """
    Pins the reminder schedule settings to the .env.example production values
    (cooldown 60), so tests never depend on whatever the local .env sets,
    and isolates tests from the real WAHA and from leaked conversation state.
    """
    from app.config import get_settings

    settings = get_settings()
    pinned = {
        "REMINDER_INTERVAL_MINUTES": 30,
        "REMINDER_COOLDOWN_MINUTES": 60,
        "MONDAY_AM_WINDOW_START": "08:00",
        "MONDAY_AM_ESCALATION_TIME": "12:00",
        "MONDAY_PM_WINDOW_START": "15:00",
        "MONDAY_PM_ESCALATION_TIME": "18:00",
        "WEEKDAY_PM_WINDOW_START": "15:00",
        "WEEKDAY_PM_ESCALATION_TIME": "18:00",
        "SATURDAY_AM_WINDOW_START": "08:00",
        "SATURDAY_AM_LAST_REMINDER": "11:30",
        "SHEETS_MAX_RETRIES": 3,
        "SHEETS_RETRY_BASE_DELAY": 1.0,
        "REMINDER_ACTIVITY_WINDOW_MINUTES": 10,
        "REMINDER_MENU_TTL_MINUTES": 120,
        "CONVERSATION_TTL_MINUTES": 30,
        "DUPLICATE_MESSAGE_WINDOW_SECONDS": 2,
    }
    for name, value in pinned.items():
        monkeypatch.setattr(settings, name, value)

    # Never talk to a real WAHA from tests: WhatsAppClient only records
    # messages in memory when it sees these placeholder values.
    monkeypatch.setattr(settings, "WAHA_BASE_URL", "http://localhost:3000")
    monkeypatch.setattr(settings, "WAHA_API_KEY", "placeholder_waha_api_key")

    # Conversation state is process-wide; don't leak it between tests.
    from app.services.conversation_service import _STORE
    _STORE.clear()

    # Per-process in-memory state of the message handler.
    from app.core import locks
    from app.whatsapp import handlers, idempotency
    locks.reset()
    idempotency.clear()
    handlers.reset_duplicate_tracking()
