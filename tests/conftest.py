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
def client():
    """FastAPI TestClient. No database overrides needed anymore."""
    with TestClient(app) as test_client:
        yield test_client
