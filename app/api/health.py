"""
Health check and system diagnostics endpoint.
"""
import logging
from fastapi import APIRouter

from app.config import get_settings
from app.core.singletons import is_sheets_connected

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    """
    Returns application health status, Google Sheets connectivity, and operational timezone.
    """
    settings = get_settings()
    try:
        # Shared client state only: the Docker healthcheck runs every 30 s, so
        # building a client here would spend Sheets quota on every probe.
        sheets_status = "connected" if is_sheets_connected() else "disconnected"
    except Exception as e:
        logger.error(f"Health check failed to verify Google Sheets connectivity: {e}")
        sheets_status = "unhealthy"

    return {
        "status": "ok",
        "app_env": settings.APP_ENV,
        "sheets": sheets_status,
        "timezone": settings.TIMEZONE
    }
