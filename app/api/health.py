"""
Health check and system diagnostics endpoint.
"""
import logging
from fastapi import APIRouter

from app.config import get_settings
from app.sheets.client import GoogleSheetsClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    """
    Returns application health status, Google Sheets connectivity, and operational timezone.
    """
    settings = get_settings()
    try:
        client = GoogleSheetsClient()
        sheets_status = "connected" if client.is_connected else "disconnected"
    except Exception as e:
        logger.error(f"Health check failed to verify Google Sheets connectivity: {e}")
        sheets_status = "unhealthy"

    return {
        "status": "ok",
        "app_env": settings.APP_ENV,
        "sheets": sheets_status,
        "timezone": settings.TIMEZONE
    }
