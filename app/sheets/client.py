"""
Google Sheets client with real Service Account authentication.
Provides convenient high‑level methods used by MastersService.
"""

import asyncio
import functools
import logging
import time
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, TypeVar

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


T = TypeVar("T")

# Module-level so tests can replace it and not really wait.
_sleep = time.sleep


def _http_status(exc: APIError) -> Optional[int]:
    """HTTP status of a gspread APIError (works across gspread 5.x/6.x)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    return status


def _is_retryable(exc: APIError) -> bool:
    """429 (quota exhausted) and 5xx are transient; 400/401/403/404 are permanent."""
    status = _http_status(exc)
    return status is not None and (status == 429 or status >= 500)


async def run_in_sheets_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Runs a blocking Sheets operation (anything that ends up in gspread/requests:
    repository, service or client methods) in the dedicated single-thread
    executor and awaits it WITHOUT blocking the event loop.

    Every call that touches Google Sheets from async code must go through
    here. The executor has exactly one worker (see app/core/singletons.py), so
    all Sheets I/O in the app is serialized on one thread: gspread/requests
    are not thread-safe, and serializing also avoids bursts of concurrent
    requests that trigger 429 "Read requests per minute per user".
    """
    # Imported lazily: app.core.singletons imports this module.
    from app.core.singletons import get_sheets_executor

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_sheets_executor(), functools.partial(func, *args, **kwargs)
    )


class GoogleSheetsClient:
    def __init__(self, credentials_path: Optional[str] = None, spreadsheet_id: Optional[str] = None):
        settings = get_settings()
        self.credentials_path = credentials_path or settings.GOOGLE_CREDENTIALS_PATH
        self.spreadsheet_id = spreadsheet_id or settings.GOOGLE_SPREADSHEET_ID
        self.is_connected: bool = False
        self._gc: Optional[Client] = None
        self._spreadsheet: Optional[Spreadsheet] = None
        # Worksheet objects by name. spreadsheet.worksheet(name) costs one
        # metadata request to Google each time; reusing the object halves the
        # requests per read/write. Only used from the Sheets thread (see
        # run_in_sheets_thread); dropped whenever an operation fails.
        self._worksheets: Dict[str, Worksheet] = {}
        self._initialize_client()

    def _with_retry(self, op: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Calls a gspread operation, retrying transient failures (429 and 5xx)
        up to SHEETS_MAX_RETRIES times with exponential backoff
        (SHEETS_RETRY_BASE_DELAY, x2, x4...). Permanent errors (400, 401, 403,
        404...) and the last failure propagate to the caller untouched.
        Runs on the Sheets thread, so the waits only delay other Sheets calls.
        NOTE: retrying a write after a 5xx can repeat it if the first attempt
        actually went through; 429 is rejected before executing, so it is safe.
        """
        settings = get_settings()
        max_retries = settings.SHEETS_MAX_RETRIES
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except APIError as exc:
                if not _is_retryable(exc) or attempt >= max_retries:
                    raise
                delay = settings.SHEETS_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Retry %d/%d for %s after %s, waiting %gs",
                    attempt + 1, max_retries, op, _http_status(exc), delay,
                )
                _sleep(delay)

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
        cached = self._worksheets.get(name)
        if cached is not None:
            return cached
        try:
            ws = self._with_retry(f"worksheet({name})", self._spreadsheet.worksheet, name)
            self._worksheets[name] = ws
            return ws
        except APIError as e:
            logger.error("API error while opening worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))
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
        self._worksheets[name] = ws
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
            records = self._with_retry(f"get_all_records({name})", ws.get_all_records)
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
            self._worksheets.pop(name, None)
            logger.error("API error while reading worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))

    def append_row(self, name: str, row: List[Any]) -> None:
        ws = self.get_worksheet(name)
        try:
            self._with_retry(f"append_row({name})", ws.append_row, row)
            logger.debug("Appended row to worksheet '%s': %s", name, row)
        except APIError as e:
            self._worksheets.pop(name, None)
            logger.error("Failed to append row to worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))

    def update_row(self, name: str, row_index: int, row: List[Any]) -> None:
        ws = self.get_worksheet(name)
        try:
            cell_range = f"A{row_index}"
            self._with_retry(f"update_row({name}, {row_index})", ws.update, cell_range, [row])
            logger.debug("Updated row %d in worksheet '%s' with %s", row_index, name, row)
        except APIError as e:
            self._worksheets.pop(name, None)
            logger.error("Failed to update row %d in worksheet '%s': %s", row_index, name, e)
            raise GoogleSheetsError(str(e))

    def batch_update_cells(self, name: str, updates: List[Dict[str, Any]]) -> None:
        """
        Writes several cells in ONE request. `updates` items look like
        {"range": "F5", "values": [["2026-09-14 15:00:00"]]} (A1 notation).
        """
        if not updates:
            return
        ws = self.get_worksheet(name)
        try:
            self._with_retry(f"batch_update({name}, {len(updates)} ranges)", ws.batch_update, updates, value_input_option="RAW")
            logger.debug("Batch-updated %d range(s) in worksheet '%s'", len(updates), name)
        except APIError as e:
            self._worksheets.pop(name, None)
            logger.error("Failed to batch-update worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))

    def find_row_index(self, name: str, key_column: int, key_value: Any) -> Optional[int]:
        """Searches a worksheet for a cell in *key_column* equal to *key_value*.
        Returns the 1‑based row index or ``None`` if not found.
        """
        ws = self.get_worksheet(name)
        try:
            cell = self._with_retry(f"find({name})", ws.find, str(key_value), in_column=key_column)
            logger.debug("Found value '%s' in column %d at row %d (worksheet '%s')", key_value, key_column, cell.row, name)
            return cell.row
        except CellNotFound:
            logger.info("Value '%s' not found in column %d of worksheet '%s'", key_value, key_column, name)
            return None
        except APIError as e:
            self._worksheets.pop(name, None)
            logger.error("Error searching worksheet '%s': %s", name, e)
            raise GoogleSheetsError(str(e))
