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
    MONDAY_CUTOFF_TIME: str = "08:30"
    REMINDER_INTERVAL_MINUTES: int = 30

    # Planning window (Mon-Fri, America/La_Paz): outside this range the bot
    # stays silent on new/free-text messages so the owner can reply manually.
    # Also bounds when automatic reminders are sent.
    PLANNING_WINDOW_START: str = "15:00"
    PLANNING_WINDOW_END: str = "18:00"

    # Escalation to the admin fires once the planning window ends (Mon-Fri).
    REMINDER_ESCALATION_TIME: str = "18:00"

    # Saturday: no periodic reminders, just a single informational notice at
    # this time to whoever hasn't registered for the upcoming Monday.
    SATURDAY_NOTICE_TIME: str = "11:45"

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
