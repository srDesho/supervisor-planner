"""
Google Sheets client with real Service Account authentication.
Provides convenient high‑level methods used by MastersService.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import gspread
from gspread import Worksheet, Spreadsheet, Client
from google.oauth2.service_account import Credentials
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound, APIError
# CellNotFound may not exist in older gspread versions
try:
    from gspread.exceptions import CellNotFound
except ImportError:
    CellNotFound = None

from app.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleSheetsError(RuntimeError):
    """Custom exception for Google Sheets client errors."""
    pass


class GoogleSheetsClient:
    def __init__(self, credentials_path: Optional[str] = None, spreadsheet_id: Optional[str] = None):
        settings = get_settings()
        self.credentials_path = credentials_path or settings.GOOGLE_CREDENTIALS_PATH
        self.spreadsheet_id = spreadsheet_id or settings.GOOGLE_SPREADSHEET_ID
        self.is_connected: bool = False
        self._gc: Optional[Client] = None
        self._spreadsheet: Optional[Spreadsheet] = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        cred_path = Path(self.credentials_path)
        if not cred_path.exists():
            logger.error(f"Google service account file not found at {cred_path}. Cannot connect to Sheets.")
            self.is_connected = False
            return
        try:
            creds = Credentials.from_service_account_file(str(cred_path), scopes=SCOPES)
            self._gc = gspread.authorize(creds)
            self._spreadsheet = self._gc.open_by_key(self.spreadsheet_id)
            self.is_connected = True
            logger.info("Connected to Google Sheets spreadsheet %s", self.spreadsheet_id)
        except SpreadsheetNotFound as e:
            logger.error("Spreadsheet with ID %s not found: %s", self.spreadsheet_id, e)
            self.is_connected = False
        except Exception as e:
            logger.exception("Unexpected error while initializing Google Sheets client: %s", e)
            self.is_connected = False

    def _ensure_connected(self) -> None:
        if not self.is_connected or self._spreadsheet is None:
            raise GoogleSheetsError("GoogleSheetsClient is not connected to a spreadsheet.")

    def get_worksheet(self, name: str) -> Worksheet:
        self._ensure_connected()
        try:
            return self._spreadsheet.worksheet(name)
        except WorksheetNotFound as e:
            logger.error("Worksheet '%s' not found in spreadsheet %s", name, self.spreadsheet_id)
            raise GoogleSheetsError(str(e))

    def worksheet_exists(self, name: str) -> bool:
        self._ensure_connected()
        try:
            self._spreadsheet.worksheet(name)
            return True
        except WorksheetNotFound:
            return False

    def create_worksheet(self, name: str, headers: List[str], rows: int = 1000) -> Worksheet:
        """Creates a new worksheet with the given header row (row 1)."""
        self._ensure_connected()
        cols = max(len(headers), 10)
        ws = self._spreadsheet.add_worksheet(title=name, rows=rows, cols=cols)
        if headers:
            ws.append_row(headers)
        logger.info("Created worksheet '%s' with %d header column(s).", name, len(headers))
        return ws

    def ensure_worksheet(self, name: str, headers: List[str]) -> bool:
        """
        Ensures a worksheet with the given name exists, creating it with
        `headers` as row 1 if it doesn't. Returns True if it already
        existed, False if it was just created.
        """
        if self.worksheet_exists(name):
            return True
        self.create_worksheet(name, headers)
        return False

    def get_all_records(self, name: str) -> List[Dict[str, Any]]:
        ws = self.get_worksheet(name)
        try:
            records = ws.get_all_records()
            logger.debug("Fetched %d records from worksheet '%s'", len(records), name)
            return records
        except IndexError:
            # gspread raises IndexError when the API returns no rows at all,
            # even if the sheet visually has headers. Treat as empty.
            logger.warning(
                "Worksheet '%s' returned no rows from the API. "
                "Treating as empty.",
                name,
            )
            return []
        except APIError as e:
            logger.error("API error while reading worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))

    def append_row(self, name: str, row: List[Any]) -> None:
        ws = self.get_worksheet(name)
        try:
            ws.append_row(row)
            logger.debug("Appended row to worksheet '%s': %s", name, row)
        except APIError as e:
            logger.error("Failed to append row to worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))

    def update_row(self, name: str, row_index: int, row: List[Any]) -> None:
        ws = self.get_worksheet(name)
        try:
            cell_range = f"A{row_index}"
            ws.update(cell_range, [row])
            logger.debug("Updated row %d in worksheet '%s' with %s", row_index, name, row)
        except APIError as e:
            logger.error("Failed to update row %d in worksheet '%s': %s", row_index, name, e)
            raise GoogleSheetsError(str(e))

    def find_row_index(self, name: str, key_column: int, key_value: Any) -> Optional[int]:
        """Searches a worksheet for a cell in *key_column* equal to *key_value*.
        Returns the 1‑based row index or ``None`` if not found.
        """
        ws = self.get_worksheet(name)
        try:
            cell = ws.find(str(key_value), in_column=key_column)
            logger.debug("Found value '%s' in column %d at row %d (worksheet '%s')", key_value, key_column, cell.row, name)
            return cell.row
        except CellNotFound:
            logger.info("Value '%s' not found in column %d of worksheet '%s'", key_value, key_column, name)
            return None
        except APIError as e:
            logger.error("Error searching worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))
