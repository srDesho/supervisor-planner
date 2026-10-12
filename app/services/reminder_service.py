"""
Reminder and escalation service — entirely over Google Sheets, no local database.

Schedule per day (America/La_Paz; every time is a setting, see app/config.py).
The machine running the bot is on from Monday ~08:00 until Saturday 12:00:
- Monday AM  [MONDAY_AM_WINDOW_START, MONDAY_AM_ESCALATION_TIME): reminders
  for TODAY (catch-up: nobody planned over the weekend). From the AM
  escalation time until the PM window opens: escalation for TODAY.
- Monday PM  [MONDAY_PM_WINDOW_START, MONDAY_PM_ESCALATION_TIME): reminders
  for TOMORROW. From the PM escalation time on: escalation for TOMORROW.
- Tuesday-Friday [WEEKDAY_PM_WINDOW_START, WEEKDAY_PM_ESCALATION_TIME):
  reminders for the NEXT work day (Friday -> Saturday). From the escalation
  time on: escalation for that day.
- Saturday [SATURDAY_AM_WINDOW_START, SATURDAY_AM_LAST_REMINDER]: reminders
  for TODAY. The tick at SATURDAY_AM_LAST_REMINDER ignores the cooldown so
  the last reminder really goes out then. No escalation on Saturday: the
  Monday AM catch-up covers it.
- Sunday: nothing.

The target date always comes from calculate_work_date(now). A supervisor is
reminded at most once per REMINDER_COOLDOWN_MINUTES (except the Saturday last
reminder). Escalation (flag the supervisor PENDIENTE_ESCALADO in
PLANIFICACION_DIARIA + alert ADMIN_PHONE) happens once per supervisor/day:
later ticks find the flag row and do nothing.
"""
import logging
from datetime import datetime, time
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.business.dates import calculate_work_date, get_weekday_code, get_current_bolivia_datetime
from app.core.locks import phone_lock, seconds_since_activity
from app.utils.phone import normalize_phone
from app.sheets.client import run_in_sheets_thread
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, is_real_planning
from app.sheets.supervisors_repository import SupervisorsRepository
from app.services.supervisor_service import SupervisorService
from app.services.conversation_service import ConversationService
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.templates import (
    MSG_REMINDER_PENDING_SUBMISSION,
    MSG_REMINDER_AWAITING_CONFIRMATION,
    MSG_REMINDER_AWAITING_SELECTION,
    MSG_REMINDER_AWAITING_RUTA_CODE,
    MSG_REMINDER_AWAITING_SELLER_CODE,
    MSG_REMINDER_MENU,
    build_escalation_alert
)

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour, minute)


class ReminderService:
    def __init__(
        self,
        whatsapp_client: Optional[WhatsAppClient] = None,
        sheets_repo: Optional[GoogleSheetsPlanningRepository] = None,
        supervisors_repo: Optional[SupervisorsRepository] = None,
        conversation_service: Optional[ConversationService] = None
    ):
        # Defaults are the process-wide singletons; tests inject fakes.
        # See app/core/singletons.py.
        from app.core.singletons import get_planning_repo, get_supervisors_repo, get_whatsapp_client
        self.settings = get_settings()
        self.sheets_repo = sheets_repo or get_planning_repo()
        self.supervisors_repo = supervisors_repo or get_supervisors_repo()
        self.supervisor_svc = SupervisorService(self.supervisors_repo)
        self.conversation_svc = conversation_service or ConversationService()
        self.whatsapp_client = whatsapp_client or get_whatsapp_client()

    async def run_reminder_cycle(self, eval_time: Optional[datetime] = None) -> None:
        now = eval_time or get_current_bolivia_datetime()
        logger.info(f"Reminder cycle tick at {now.isoformat()} (weekday={now.weekday()})")
        weekday = now.weekday()
        # Compare at minute resolution: a tick at 11:30:00.4 is the 11:30 tick.
        t = time(now.hour, now.minute)
        s = self.settings

        if weekday == 6:
            logger.debug("Reminder cycle skipped: Sunday, the bot is not expected to be running.")
            return

        if weekday == 5:
            sat_start = _parse_hhmm(s.SATURDAY_AM_WINDOW_START)
            sat_last = _parse_hhmm(s.SATURDAY_AM_LAST_REMINDER)
            if sat_start <= t <= sat_last:
                await self._run_normal_reminders(now, ignore_cooldown=(t == sat_last))
            return

        if weekday == 0:
            am_start = _parse_hhmm(s.MONDAY_AM_WINDOW_START)
            am_escalation = _parse_hhmm(s.MONDAY_AM_ESCALATION_TIME)
            pm_start = _parse_hhmm(s.MONDAY_PM_WINDOW_START)
            pm_escalation = _parse_hhmm(s.MONDAY_PM_ESCALATION_TIME)
            if am_start <= t < am_escalation:
                await self._run_normal_reminders(now)
            elif am_escalation <= t < pm_start:
                await self._run_escalation(now)
            elif pm_start <= t < pm_escalation:
                await self._run_normal_reminders(now)
            elif t >= pm_escalation:
                await self._run_escalation(now)
            return

        # Tuesday-Friday
        pm_start = _parse_hhmm(s.WEEKDAY_PM_WINDOW_START)
        pm_escalation = _parse_hhmm(s.WEEKDAY_PM_ESCALATION_TIME)
        if pm_start <= t < pm_escalation:
            await self._run_normal_reminders(now)
        elif t >= pm_escalation:
            await self._run_escalation(now)

    async def _run_normal_reminders(self, now: datetime, ignore_cooldown: bool = False) -> None:
        """
        One reminder tick. Google Sheets cost of a tick, however many supervisors:
        SUPERVISORES comes from its cache, PLANIFICACION_DIARIA is read ONCE,
        and Ultimo_Recordatorio is written ONCE (one batch) -- and only if a
        reminder was actually sent.
        """
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        dia_trabajo = get_weekday_code(fecha_trabajo)
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")

        sent = 0
        failed = 0
        skipped_registered = 0
        skipped_cooldown = 0
        skipped_active = 0

        supervisors = await run_in_sheets_thread(self.supervisor_svc.get_all_active)

        # 1) Cooldown first. It is decided from the (cached) SUPERVISORES rows,
        #    so anyone reminded recently costs no read of PLANIFICACION_DIARIA.
        candidates = []
        for supervisor in supervisors:
            if not ignore_cooldown and self._within_cooldown(supervisor, now):
                skipped_cooldown += 1
            else:
                candidates.append(supervisor)

        planning_index: Dict[Any, Any] = {}
        if candidates:
            # 2) ONE read of PLANIFICACION_DIARIA for the whole tick; every
            #    "has this supervisor planned?" below is answered from memory.
            try:
                planning_index = await run_in_sheets_thread(self.sheets_repo.read_active_index)
            except Exception as exc:
                # Without it we cannot tell who already planned: remind nobody
                # rather than nag people who did. The next tick retries.
                logger.error(f"Reminder tick aborted, could not read PLANIFICACION_DIARIA: {exc}", exc_info=True)
                return

        reminded: Dict[str, str] = {}
        for supervisor in candidates:
            try:
                key = (fecha_trabajo_str, supervisor.get("Sede", ""), supervisor.get("Nombre", ""))
                if is_real_planning(planning_index.get(key)):
                    skipped_registered += 1
                    continue

                # Defensive: gspread may return numeric cells as int/float.
                # Proactive sends always go to the Sheet's Telefono; the
                # client turns it into '<digits>@c.us' (591 prefix if 8 digits).
                phone = str(supervisor.get("Telefono", "") or "")

                # Same per-phone lock as the message handler, so a reminder can
                # never slip in between a question and the supervisor's answer.
                async with phone_lock(normalize_phone(phone)):
                    if self._recently_active(phone):
                        skipped_active += 1
                        continue
                    conv_phone = normalize_phone(phone)
                    entry = self.conversation_svc.get(conv_phone)
                    state = entry["state"] if entry else None
                    msg = self._build_reminder_message(supervisor, fecha_trabajo, dia_trabajo)
                    await self.whatsapp_client.send_message(phone, msg)
                    if state in (None, "AWAITING_MAIN_MENU"):
                        # The reminder ends with the numbered main menu: leave the supervisor
                        # at that menu (for longer than a normal conversation) so "1".."4"
                        # answers it, even if they reply much later.
                        self.conversation_svc.set(
                            conv_phone, "AWAITING_MAIN_MENU", payload={},
                            ttl_minutes=self.settings.REMINDER_MENU_TTL_MINUTES
                        )
                    # The cooldown must hold from now on; the Sheet is written in
                    # one batch at the end of the tick. (Memory only, no Sheets I/O.)
                    self.supervisors_repo.stamp_last_reminder_in_cache(phone, stamp)
                    reminded[phone] = stamp
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

        if reminded:
            try:
                await run_in_sheets_thread(self.supervisors_repo.update_last_reminders, reminded)
            except Exception as exc:
                logger.error(
                    f"Could not persist Ultimo_Recordatorio for {len(reminded)} supervisor(s): {exc}",
                    exc_info=True,
                )

        logger.info(
            f"Normal reminders for {fecha_trabajo_str} done: {sent} sent, {failed} failed, "
            f"{skipped_registered} already registered, {skipped_cooldown} within cooldown, "
            f"{skipped_active} writing to the bot right now."
        )

    def _recently_active(self, phone: str) -> bool:
        """
        True if this supervisor wrote to the bot within
        REMINDER_ACTIVITY_WINDOW_MINUTES: they are in a live conversation (with
        or without a pending state) and must not be interrupted.
        """
        seconds = seconds_since_activity(normalize_phone(phone))
        return seconds is not None and seconds < self.settings.REMINDER_ACTIVITY_WINDOW_MINUTES * 60

    def _build_reminder_message(self, supervisor: Dict[str, Any], fecha_trabajo, dia_trabajo: str) -> str:
        conv_phone = normalize_phone(supervisor.get("Telefono", ""))
        entry = self.conversation_svc.get(conv_phone)
        if entry and entry["state"] == "AWAITING_CONFIRMATION":
            return MSG_REMINDER_AWAITING_CONFIRMATION
        if entry and entry["state"] == "AWAITING_SELECTION":
            return MSG_REMINDER_AWAITING_SELECTION
        if entry and entry["state"] == "AWAITING_RUTA_CODE":
            return MSG_REMINDER_AWAITING_RUTA_CODE
        if entry and entry["state"] == "AWAITING_SELLER_CODE":
            return MSG_REMINDER_AWAITING_SELLER_CODE
        # Menu 5: "no planning yet" reminder + the numbered main menu.
        pending = MSG_REMINDER_PENDING_SUBMISSION.format(
            fecha=fecha_trabajo.strftime("%d/%m/%Y"), dia=dia_trabajo
        )
        return f"{pending}\n\n{MSG_REMINDER_MENU}"

    def _within_cooldown(self, supervisor: Dict[str, Any], now: datetime) -> bool:
        last = self._parse_timestamp(supervisor.get("Ultimo_Recordatorio"))
        if not last:
            return False
        cooldown_seconds = self.settings.REMINDER_COOLDOWN_MINUTES * 60
        return (now.replace(tzinfo=None) - last).total_seconds() < cooldown_seconds

    async def _run_escalation(self, now: datetime) -> None:
        """
        Flags every supervisor without a planning for the target date as
        PENDIENTE_ESCALADO and alerts the admin about them. Idempotent:
        mark_escalated() writes nothing if a row (real planning or an earlier
        escalation) already exists, and only newly escalated supervisors go
        into the alert, so repeated ticks create neither duplicate rows nor
        duplicate alerts.
        """
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        pendientes: List[Dict[str, Any]] = []

        supervisors = await run_in_sheets_thread(self.supervisor_svc.get_all_active)
        if not supervisors:
            return
        # ONE read of PLANIFICACION_DIARIA per tick. Ticks keep coming after the
        # cutoff until midnight, but once everyone has a row (a planning or an
        # escalation flag) they cost just this single read and write nothing.
        try:
            planning_index = await run_in_sheets_thread(self.sheets_repo.read_active_index)
        except Exception as exc:
            logger.error(f"Escalation tick aborted, could not read PLANIFICACION_DIARIA: {exc}", exc_info=True)
            return

        for supervisor in supervisors:
            key = (fecha_trabajo_str, supervisor.get("Sede", ""), supervisor.get("Nombre", ""))
            if key in planning_index:
                continue  # a real planning, or already escalated: nothing to do
            try:
                # mark_escalated re-checks right before writing (it is the guard
                # against a second process/instance creating the same flag row).
                result = await run_in_sheets_thread(
                    self.sheets_repo.mark_escalated,
                    fecha_trabajo_str, supervisor.get("Sede", ""), supervisor.get("Nombre", "")
                )
                if result.get("__created"):
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
