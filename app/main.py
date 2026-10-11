"""
FastAPI application entrypoint for Supervisor Planner.
Handles application lifecycle (Google Sheets startup checks, scheduler startup/shutdown) and router registration.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, setup_logging
from app.core.singletons import (
    get_audit_repo, get_masters_service, init_singletons, shutdown_singletons,
)
from app.sheets.client import run_in_sheets_thread
from app.services.scheduler_service import start_scheduler, shutdown_scheduler
from app.api import health, webhook

settings = get_settings()
setup_logging(settings)
logger = logging.getLogger(__name__)


async def _startup_sheet_checks() -> None:
    """Warm-up that talks to Google Sheets. Failures here are logged, not fatal."""
    # All Sheets I/O goes through the single Sheets thread, never the event loop.
    try:
        already_existed = await run_in_sheets_thread(get_audit_repo().ensure_sheet)
        logger.info("Pestaña LOG_BOT %s" % ("encontrada" if already_existed else "creada"))
    except Exception as e:
        logger.error(f"Error verificando/creando LOG_BOT en Google Sheets al arrancar: {e}")

    logger.info("Loading masters cache at startup...")
    # A failed preload (e.g. a transient 429) must not crash-loop the container:
    # ensure_loaded() never raises and the cache is retried lazily on first use.
    loaded = await run_in_sheets_thread(get_masters_service().ensure_loaded)
    if loaded:
        logger.info("Masters cache loaded successfully at startup.")
    else:
        logger.error("Masters cache could NOT be loaded at startup. Bot will return empty results until next successful refresh.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Build the process-wide singletons (Sheets client, repositories, caches, services).
    # If any cannot be built this raises and the app does NOT start: better to fail
    # here than on the first WhatsApp message.
    init_singletons()

    await _startup_sheet_checks()

    if not settings.DEBUG:
        start_scheduler()
    yield
    # Shutdown: gracefully close background services
    shutdown_scheduler()
    shutdown_singletons()


app = FastAPI(
    title="Supervisor Planner Bot",
    description="Backend automatizado para captura y consolidación de planificaciones de supervisores comerciales vía WhatsApp.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(health.router)
app.include_router(webhook.router)


@app.get("/")
def root():
    return {
        "app": "Supervisor Planner",
        "status": "online",
        "docs_url": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )
