"""
Process-wide singletons: the objects that must exist exactly ONCE.

WHY singletons (read this before "simplifying" them back to `X()` per use):
- Building a GoogleSheetsClient authenticates against Google and opens the
  spreadsheet (network calls). The old code built three of them (plus an empty
  MastersService and a new SupervisorsRepository) for EVERY WhatsApp message
  and every reminder tick, which burned the Sheets quota
  (429 "Read requests per minute per user", limit 60).
- The in-memory caches (masters, supervisors, worksheet objects) only work if
  the same instance lives for the whole process. A fresh instance per message
  means the cache is always cold.
- gspread/requests are not thread-safe, so every Sheets call must also go
  through the single-worker executor created here
  (see app.sheets.client.run_in_sheets_thread).

All of this assumes ONE uvicorn worker: each worker process would have its own
copy of these objects, caches and in-memory conversation state.

Startup: main.py calls init_singletons(). If building any of them fails the
app does not start (better than failing on the first message).

Tests build their own objects with injected fakes and never need this module,
except to test the singletons themselves (see reset_singletons()).
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.sheets.client import GoogleSheetsClient, GoogleSheetsError
from app.sheets.masters import MastersService
from app.sheets.supervisors_repository import SupervisorsRepository
from app.sheets.planning_repository import GoogleSheetsPlanningRepository
from app.sheets.audit_repository import AuditRepository
from app.whatsapp.client import WhatsAppClient
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.planning_service import PlanningService
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)

# RLock: getters call each other (e.g. get_planning_service -> get_planning_repo).
_lock = threading.RLock()
_instances: dict = {}


def _get_or_build(key: str, factory):
    with _lock:
        if key not in _instances:
            _instances[key] = factory()
        return _instances[key]


def get_sheets_executor() -> ThreadPoolExecutor:
    """The ONE thread that performs all Google Sheets I/O (max_workers=1 on purpose)."""
    return _get_or_build(
        "executor", lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="sheets")
    )


def get_sheets_client() -> GoogleSheetsClient:
    """The single Sheets client shared by SUPERVISORES, PLANIFICACION_DIARIA, LOG_BOT and the masters."""
    def build() -> GoogleSheetsClient:
        client = GoogleSheetsClient()
        if not client.is_connected:
            raise GoogleSheetsError("GoogleSheetsClient not connected – check credentials and spreadsheet id.")
        return client

    return _get_or_build("client", build)


def get_masters_service() -> MastersService:
    return _get_or_build("masters", lambda: MastersService(client=get_sheets_client()))


def get_supervisors_repo() -> SupervisorsRepository:
    return _get_or_build("supervisors_repo", lambda: SupervisorsRepository(client=get_sheets_client()))


def get_planning_repo() -> GoogleSheetsPlanningRepository:
    return _get_or_build("planning_repo", lambda: GoogleSheetsPlanningRepository(client=get_sheets_client()))


def get_audit_repo() -> AuditRepository:
    return _get_or_build("audit_repo", lambda: AuditRepository(client=get_sheets_client()))


def get_supervisor_service() -> SupervisorService:
    return _get_or_build("supervisor_service", lambda: SupervisorService(repo=get_supervisors_repo()))


def get_audit_service() -> AuditService:
    return _get_or_build("audit_service", lambda: AuditService(repo=get_audit_repo()))


def get_whatsapp_client() -> WhatsAppClient:
    return _get_or_build("whatsapp_client", WhatsAppClient)


def get_planning_service() -> PlanningService:
    """PlanningService keeps no per-message state, so one instance serves every message."""
    return _get_or_build("planning_service", lambda: PlanningService(
        whatsapp_client=get_whatsapp_client(),
        sheets_repo=get_planning_repo(),
        masters_service=get_masters_service(),
        supervisor_service=get_supervisor_service(),
        audit_service=get_audit_service(),
    ))


def get_reminder_service() -> ReminderService:
    return _get_or_build("reminder_service", lambda: ReminderService(
        whatsapp_client=get_whatsapp_client(),
        sheets_repo=get_planning_repo(),
        supervisors_repo=get_supervisors_repo(),
    ))


def init_singletons(client: Optional[GoogleSheetsClient] = None) -> None:
    """
    Builds every singleton now. Raises if any of them cannot be built, so the
    app fails at startup instead of on the first message.
    `client` lets tests inject a fake Sheets client.
    """
    with _lock:
        if client is not None:
            _instances["client"] = client
        get_sheets_executor()
        get_sheets_client()
        get_masters_service()
        get_supervisors_repo()
        get_planning_repo()
        get_audit_repo()
        get_supervisor_service()
        get_audit_service()
        get_whatsapp_client()
        get_planning_service()
        get_reminder_service()
    logger.info("Singletons initialized (1 Sheets client, 1 Sheets thread).")


def is_sheets_connected() -> bool:
    """Connection state of the shared client, without building or contacting anything."""
    client = _instances.get("client")
    return bool(client is not None and client.is_connected)


def shutdown_singletons() -> None:
    """Stops the Sheets thread. Called on app shutdown."""
    with _lock:
        # Popped (not just shut down) so a later get_sheets_executor() builds a fresh one.
        executor = _instances.pop("executor", None)
        if executor is not None:
            executor.shutdown(wait=False)


def reset_singletons() -> None:
    """Testing helper: forgets every singleton (and stops the Sheets thread)."""
    with _lock:
        shutdown_singletons()
        _instances.clear()
