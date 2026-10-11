"""
Reminder and escalation service — entirely over Google Sheets, no local database.

Schedule (see PARTE 7 / K / L / M of the spec):
- Monday-Friday, within [PLANNING_WINDOW_START, PLANNING_WINDOW_END]: a
  reminder every REMINDER_INTERVAL_MINUTES to whoever hasn't registered yet.
  At REMINDER_ESCALATION_TIME (window close), escalate instead: mark
  PENDIENTE_ESCALADO in PLANIFICACION_DIARIA and alert ADMIN_PHONE.
- Saturday, at SATURDAY_NOTICE_TIME: a single informational notice to
  whoever hasn't registered for the upcoming Monday, plus the same
  escalation treatment (mark + admin alert) per decision L — never repeated
  the same day.
- Sunday: nothing at all.
"""
import logging
from datetime import datetime, time
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.business.dates import calculate_work_date, get_weekday_code, get_current_bolivia_datetime
from app.utils.phone import normalize_phone
from app.sheets.planning_repository import GoogleSheetsPlanningRepository
from app.sheets.supervisors_repository import SupervisorsRepository
from app.services.supervisor_service import SupervisorService
from app.services.conversation_service import ConversationService
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.templates import (
    MSG_REMINDER_PENDING_SUBMISSION,
    MSG_REMINDER_AWAITING_CONFIRMATION,
    MSG_REMINDER_AWAITING_SELECTION,
    MSG_REMINDER_SATURDAY_NOTICE,
    build_escalation_alert
)

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(
        self,
        whatsapp_client: Optional[WhatsAppClient] = None,
        sheets_repo: Optional[GoogleSheetsPlanningRepository] = None,
        supervisors_repo: Optional[SupervisorsRepository] = None,
        conversation_service: Optional[ConversationService] = None
    ):
        self.settings = get_settings()
        self.sheets_repo = sheets_repo or GoogleSheetsPlanningRepository()
        self.supervisors_repo = supervisors_repo or SupervisorsRepository()
        self.supervisor_svc = SupervisorService(self.supervisors_repo)
        self.conversation_svc = conversation_service or ConversationService()
        self.whatsapp_client = whatsapp_client or WhatsAppClient()

    async def run_reminder_cycle(self, eval_time: Optional[datetime] = None) -> None:
        now = eval_time or get_current_bolivia_datetime()
        logger.info(f"Reminder cycle tick at {now.isoformat()} (weekday={now.weekday()})")
        weekday = now.weekday()

        if weekday == 6:
            logger.debug("Reminder cycle skipped: Sunday is not a work day.")
            return

        if weekday == 5:
            notice_hour, notice_minute = map(int, self.settings.SATURDAY_NOTICE_TIME.split(":"))
            notice_time = time(notice_hour, notice_minute)
            if now.time() >= notice_time:
                await self._run_saturday_notice(now)
            return

        start_hour, start_minute = map(int, self.settings.PLANNING_WINDOW_START.split(":"))
        end_hour, end_minute = map(int, self.settings.PLANNING_WINDOW_END.split(":"))
        window_start = time(start_hour, start_minute)
        window_end = time(end_hour, end_minute)
        if not (window_start <= now.time() <= window_end):
            return

        escalation_hour, escalation_minute = map(int, self.settings.REMINDER_ESCALATION_TIME.split(":"))
        escalation_time = time(escalation_hour, escalation_minute)
        if now.time() >= escalation_time:
            await self._run_escalation(now)
            return

        await self._run_normal_reminders(now)

    async def _run_normal_reminders(self, now: datetime) -> None:
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        dia_trabajo = get_weekday_code(fecha_trabajo)

        sent = 0
        failed = 0
        skipped_registered = 0
        skipped_cooldown = 0

        for supervisor in self.supervisor_svc.get_all_active():
            try:
                if self._has_active_planning(fecha_trabajo_str, supervisor):
                    skipped_registered += 1
                    continue
                if self._within_cooldown(supervisor, now):
                    skipped_cooldown += 1
                    continue

                # Defensive: gspread may return numeric cells as int/float.
                # Proactive sends always go to the Sheet's Telefono; the
                # client turns it into '<digits>@c.us' (591 prefix if 8 digits).
                phone = str(supervisor.get("Telefono", "") or "")

                msg = self._build_reminder_message(supervisor, fecha_trabajo, dia_trabajo)
                await self.whatsapp_client.send_message(phone, msg)
                self.supervisors_repo.update_last_reminder(phone, now.strftime("%Y-%m-%d %H:%M:%S"))
                logger.info(f"Dispatched reminder to {supervisor.get('Nombre')} ({phone}).")
                sent += 1
            except Exception as exc:
                failed += 1
                logger.error(
                    f"Failed to send reminder to {supervisor.get('Nombre')} "
                    f"({supervisor.get('Telefono')}): {exc}",
                    exc_info=True,
                )
                continue

        logger.info(
            f"Normal reminders done: {sent} sent, {failed} failed, "
            f"{skipped_registered} already registered, {skipped_cooldown} within cooldown."
        )

    def _build_reminder_message(self, supervisor: Dict[str, Any], fecha_trabajo, dia_trabajo: str) -> str:
        conv_phone = normalize_phone(supervisor.get("Telefono", ""))
        entry = self.conversation_svc.get(conv_phone)
        if entry and entry["state"] == "AWAITING_CONFIRMATION":
            return MSG_REMINDER_AWAITING_CONFIRMATION
        if entry and entry["state"] == "AWAITING_SELECTION":
            return MSG_REMINDER_AWAITING_SELECTION
        return MSG_REMINDER_PENDING_SUBMISSION.format(
            fecha=fecha_trabajo.strftime("%d/%m/%Y"), dia=dia_trabajo
        )

    def _has_active_planning(self, fecha_trabajo_str: str, supervisor: Dict[str, Any]) -> bool:
        row = self.sheets_repo.find_active(
            fecha_trabajo_str, supervisor.get("Sede", ""), supervisor.get("Nombre", "")
        )
        return row is not None and row.get("Estado") != "CANCELADO"

    def _within_cooldown(self, supervisor: Dict[str, Any], now: datetime) -> bool:
        last = self._parse_timestamp(supervisor.get("Ultimo_Recordatorio"))
        if not last:
            return False
        interval_seconds = self.settings.REMINDER_INTERVAL_MINUTES * 60
        return (now.replace(tzinfo=None) - last).total_seconds() < interval_seconds

    async def _run_escalation(self, now: datetime) -> None:
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        pendientes: List[Dict[str, Any]] = []

        for supervisor in self.supervisor_svc.get_all_active():
            try:
                if self._has_active_planning(fecha_trabajo_str, supervisor):
                    continue
                self.sheets_repo.mark_escalated(
                    fecha_trabajo_str, supervisor.get("Sede", ""), supervisor.get("Nombre", "")
                )
                pendientes.append(supervisor)
            except Exception as exc:
                logger.error(
                    f"Failed to escalate {supervisor.get('Nombre')}: {exc}",
                    exc_info=True,
                )
                continue

        if pendientes:
            await self._send_escalation_alert(fecha_trabajo.strftime("%d/%m/%Y"), pendientes)
            logger.warning(f"Dispatched escalation alert to admin for {len(pendientes)} supervisors.")

    async def _run_saturday_notice(self, now: datetime) -> None:
        """
        Single Saturday event: sends the informational notice AND applies
        the same escalation treatment (PENDIENTE_ESCALADO + admin alert) as
        Mon-Fri, per decision L ("Opción A"). Deduplicated per calendar day
        via Ultimo_Recordatorio's date, so later ticks the same Saturday
        don't repeat it.
        """
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        pendientes: List[Dict[str, Any]] = []

        for supervisor in self.supervisor_svc.get_all_active():
            try:
                if self._has_active_planning(fecha_trabajo_str, supervisor):
                    continue

                last = self._parse_timestamp(supervisor.get("Ultimo_Recordatorio"))
                if last and last.date() == now.date():
                    continue

                phone = str(supervisor.get("Telefono", "") or "")

                await self.whatsapp_client.send_message(phone, MSG_REMINDER_SATURDAY_NOTICE)
                self.supervisors_repo.update_last_reminder(phone, now.strftime("%Y-%m-%d %H:%M:%S"))
                logger.info(f"Dispatched Saturday notice to {supervisor.get('Nombre')} ({phone}).")

                self.sheets_repo.mark_escalated(
                    fecha_trabajo_str, supervisor.get("Sede", ""), supervisor.get("Nombre", "")
                )
                pendientes.append(supervisor)
            except Exception as exc:
                logger.error(
                    f"Failed to send Saturday notice to {supervisor.get('Nombre')}: {exc}",
                    exc_info=True,
                )
                continue

        if pendientes:
            await self._send_escalation_alert(fecha_trabajo.strftime("%d/%m/%Y"), pendientes)
            logger.warning(f"Dispatched Saturday escalation alert to admin for {len(pendientes)} supervisors.")

    async def _send_escalation_alert(self, fecha_trabajo_display: str, pendientes: List[Dict[str, Any]]) -> None:
        msg = build_escalation_alert(
            fecha_trabajo=fecha_trabajo_display,
            uncompleted_supervisors=[
                {"sede": s.get("Sede", ""), "supervisor": s.get("Nombre", "")} for s in pendientes
            ]
        )
        await self.whatsapp_client.send_message(str(self.settings.ADMIN_PHONE), msg)

    @staticmethod
    def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt)
            except (ValueError, TypeError):
                continue
        return None