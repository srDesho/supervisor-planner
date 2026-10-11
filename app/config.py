"""
Application configuration management using Pydantic Settings.
Centralizes all environment variables and provides structured logging setup.
"""
from functools import lru_cache
import logging
import sys
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General application configuration
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Timezone and business operational rules
    TIMEZONE: str = "America/La_Paz"

    # Reminder scheduler: how often the cycle ticks, and the minimum gap
    # between two reminders to the same supervisor.
    REMINDER_INTERVAL_MINUTES: int = 30
    REMINDER_COOLDOWN_MINUTES: int = 60

    # Reminder schedule per day (America/La_Paz). Reminders target the next
    # work day (see app/business/dates.py) except Monday AM and Saturday AM,
    # which target the same day. At an *_ESCALATION_TIME the cycle stops
    # reminding and escalates to the admin (once per supervisor/day).
    # Monday: AM catch-up window (target: today), then the usual PM window.
    MONDAY_AM_WINDOW_START: str = "08:00"
    MONDAY_AM_ESCALATION_TIME: str = "12:00"
    MONDAY_PM_WINDOW_START: str = "15:00"
    MONDAY_PM_ESCALATION_TIME: str = "18:00"
    # Tuesday-Friday: PM window only.
    WEEKDAY_PM_WINDOW_START: str = "15:00"
    WEEKDAY_PM_ESCALATION_TIME: str = "18:00"
    # Saturday: AM window only (target: today), no escalation (the machine
    # is switched off at 12:00).
    SATURDAY_AM_WINDOW_START: str = "08:00"
    SATURDAY_AM_LAST_REMINDER: str = "11:30"

    # Conversation state and supervisors cache (both in-memory; see
    # app/services/conversation_service.py and app/sheets/supervisors_repository.py)
    CONVERSATION_TTL_MINUTES: int = 30
    SUPERVISORS_CACHE_TTL_SECONDS: int = 300

    # Google Sheets Configuration — all persistence lives here, no local database.
    GOOGLE_CREDENTIALS_PATH: str = "credentials/credentials.json"
    GOOGLE_SPREADSHEET_ID: str = "placeholder_spreadsheet_id"
    GOOGLE_WORKSHEET_SCZ: str = "PLANIFICACION_SCZ_RENOM"
    GOOGLE_WORKSHEET_CBBA: str = "PLANIFICACION_CBBA_RENOM"
    GOOGLE_WORKSHEET_LPZ: str = "PLANIFICACION_LPZ"
    GOOGLE_OUTPUT_WORKSHEET: str = "PLANIFICACION_DIARIA"
    GOOGLE_WORKSHEET_SUPERVISORS: str = "SUPERVISORES"
    GOOGLE_WORKSHEET_LOG: str = "LOG_BOT"
    SHEETS_CACHE_TTL_SECONDS: int = 1800

    # Google Gemini API
    GEMINI_API_KEY: str = "placeholder_gemini_api_key"
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SECONDS: int = 10

    # WAHA (WhatsApp HTTP API)
    WAHA_BASE_URL: str = "http://localhost:3000"
    WAHA_API_KEY: str = "placeholder_waha_api_key"
    WAHA_SESSION: str = "default"

    # Administration and Alerts — ADMIN_PHONE in local 8-digit format (no
    # country code), same convention as all other phone numbers in the system.
    ADMIN_PHONE: str = "70000000"
    STATUS_GROUP_ID: Optional[str] = None


@lru_cache()
def get_settings() -> Settings:
    """Returns a cached singleton instance of Settings."""
    return Settings()


def setup_logging(settings: Settings) -> None:
    """Configures structured standard logging for the application."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    # Ensure logs directory exists if logging to file
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / "supervisor_planner.log", encoding="utf-8")
        ]
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
