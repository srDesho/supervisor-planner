"""
Core planning orchestrator service.

Flow (see PARTE 6 of the spec): resolve sender phone -> authenticate ->
AYUDA -> conversational state (AWAITING_CONFIRMATION / AWAITING_SELECTION /
AWAITING_RUTA_CODE) -> new planning (seller code, RUTA, VENTA DIRECTA,
OFICINA). Incoming messages are attended at any day/hour; the schedule only
governs the proactive reminders (see reminder_service).

Silence policy: unresolvable senders and unauthorized phones get ZERO trace
(no reply, no LOG_BOT). Authenticated supervisors always get an audit trail,
even when ignored for being outside the planning window.
"""
import logging
from typing import Any, Dict, Optional
from datetime import datetime

from app.config import get_settings
from app.business.dates import calculate_work_date, get_weekday_code, get_current_bolivia_datetime
from app.business.planning_rules import (
    build_confirmation_summary,
    build_confirmation_summary_update,
    build_selection_prompt,
    build_current_plan_message,
    build_route_list,
    route_list_pages,
    weekday_name_es
)
from app.whatsapp.parser import (
    ParsedWhatsAppMessage, extract_planning_intent, extract_ruta_input, normalize_command,
    parse_menu_choice, parse_number
)
from app.whatsapp.lid_resolver import resolve_to_phone
from app.whatsapp.templates import (
    MSG_MAIN_MENU,
    MSG_MAIN_MENU_KEEP,
    MSG_KEEP_PLAN_OK,
    MSG_NOTHING_PENDING,
    MSG_MAIN_MENU_COMMANDS_HINT,
    MSG_RUTA_MENU,
    MSG_ASK_SELLER_CODE,
    MSG_ASK_ROUTE_CODE,
    MSG_SELLER_CODE_INVALID,
    MSG_ROUTE_CODE_INVALID,
    MSG_LIST_PICK_INVALID,
    MSG_ROUTE_CODE_NOT_FOUND,
    MSG_SELLER_CODE_NOT_FOUND,
    MSG_SELLER_NO_ROUTE_TODAY,
    MSG_SUPERVISOR_NO_ZONE,
    MSG_SELLER_WRONG_ZONE,
    MSG_SELLER_ALREADY_ASSIGNED,
    MSG_REGISTERED_OK,
    MSG_UPDATED_OK,
    MSG_NO_PLAN_INFO,
    MSG_PLAN_ALREADY_ACTIVE,
    MSG_CANCELLED_NO_CHANGES,
    MSG_SELECTION_INVALID,
    MSG_SELECTION_TOO_MANY_ERRORS,
    MSG_RUTA_CODE_NOT_FOUND,
    MSG_RUTA_LIST_OUT_OF_RANGE,
    MSG_RUTA_LIST_EMPTY,
    MSG_RUTA_LIST_BAD_PAGE
)
from app.whatsapp.client import WhatsAppClient
from app.sheets.client import run_in_sheets_thread
from app.sheets.masters import MastersService
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, is_real_planning, same_planning
from app.services.supervisor_service import SupervisorService
from app.services.conversation_service import ConversationService
from app.services.audit_service import AuditService

MAX_SELECTION_ATTEMPTS = 3

MODALIDAD_ACOMPANAMIENTO = "ACOMPAÑAMIENTO"
MODALIDAD_RUTA = "RUTA"

# Menu 3 (the confirmation summary): option number -> the intent it stands for.
_CONFIRMATION_MENU = {1: "confirm", 2: "correct", 3: "cancel"}

logger = logging.getLogger(__name__)


class PlanningService:
    def __init__(
        self,
        whatsapp_client: Optional[WhatsAppClient] = None,
        sheets_repo: Optional[GoogleSheetsPlanningRepository] = None,
        masters_service: Optional[MastersService] = None,
        supervisor_service: Optional[SupervisorService] = None,
        conversation_service: Optional[ConversationService] = None,
        audit_service: Optional[AuditService] = None
    ):
        # Defaults are the process-wide singletons (one Sheets client, warm caches);
        # tests inject their own fakes. See app/core/singletons.py.
        from app.core.singletons import (
            get_audit_service, get_masters_service, get_planning_repo,
            get_supervisor_service, get_whatsapp_client,
        )
        self.settings = get_settings()
        self.supervisor_svc = supervisor_service or get_supervisor_service()
        self.conversation_svc = conversation_service or ConversationService()
        self.audit_svc = audit_service or get_audit_service()

        self.whatsapp_client = whatsapp_client or get_whatsapp_client()
        self.sheets_repo = sheets_repo or get_planning_repo()
        self.masters_service = masters_service or get_masters_service()

    async def handle_message(
        self,
        msg: ParsedWhatsAppMessage,
        eval_datetime: Optional[datetime] = None
    ) -> None:
        chat_id = msg.from_full or msg.from_phone
        text = msg.body
        message_id = msg.message_id

        # 1. Resolve the sender's real phone number. Unresolvable senders
        # get zero trace (lid_resolver already logs a WARNING to stdout).
        phone = await resolve_to_phone(chat_id)
        if not phone:
            return

        # 2. Authenticate. Not in SUPERVISORES (or inactive) => zero trace.
        supervisor = await run_in_sheets_thread(self.supervisor_svc.authenticate, phone)
        if not supervisor:
            return

        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]

        intent = extract_planning_intent(text)

        # 3. Conversational state (in-memory, keyed by phone).
        now = eval_datetime or get_current_bolivia_datetime()
        entry = self.conversation_svc.get(phone)
        step = entry["state"] if entry else "IDLE"
        fecha_trabajo = calculate_work_date(now)

        # AYUDA is available in any state; what it shows depends on the step.
        if intent["type"] == "help":
            await self._handle_help(step, entry, supervisor, phone, chat_id, fecha_trabajo)
            return

        if step == "IDLE":
            # CORREGIR with nothing pending is an explicit request to look at the saved
            # plan, so it is answered instead of falling into the silence rule below.
            if intent["type"] == "correct":
                await self._handle_correct(supervisor, phone, chat_id, fecha_trabajo)
                return

            # Silencio después de registrado: si ya tiene plan activo para la fecha y está en IDLE.
            # Una fila PENDIENTE_ESCALADO no es un plan: quien fue escalado planifica con normalidad.
            active = await run_in_sheets_thread(
                self.sheets_repo.find_active,
                fecha_trabajo.strftime("%Y-%m-%d"),
                sede, supervisor_name
            )
            if is_real_planning(active) and intent["type"] in ("unknown", "confirm", "correct"):
                await run_in_sheets_thread(
                    self.audit_svc.log,
                    phone=phone,
                    whatsapp_id=chat_id,
                    supervisor=supervisor_name,
                    sede=sede,
                    whatsapp_message_id=message_id,
                    original_message=text,
                    action="IGNORED_ALREADY_REGISTERED",
                    result="IGNORED",
                    details="Mensaje ignorado: supervisor ya tiene plan activo para la fecha y estado es IDLE"
                )
                return

            if is_real_planning(active) and intent["type"] == "cancel":
                # Nothing is pending, so there is nothing to cancel; say so instead of offering the menu.
                await self.whatsapp_client.send_message(chat_id, MSG_NOTHING_PENDING)
                return

            # 4. New planning (an unknown message without a saved plan gets the main menu).
            await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)
            return

        if step == "AWAITING_CONFIRMATION":
            # Menu 3: 1 / 2 / 3 stand for CONFIRMAR / CORREGIR / CANCELAR (words still work).
            choice = parse_menu_choice(text)
            if choice in _CONFIRMATION_MENU:
                intent = {"type": _CONFIRMATION_MENU[choice], "codigo_erp": None, "raw": text}
            await self._handle_awaiting_confirmation(intent, entry, supervisor, phone, chat_id, message_id, now)
            return

        if step == "AWAITING_SELECTION":
            await self._handle_awaiting_selection(text, entry, supervisor, phone, chat_id)
            return

        if step == "AWAITING_MAIN_MENU":
            await self._handle_awaiting_main_menu(text, intent, entry, supervisor, phone, chat_id, message_id, now)
            return

        if step == "AWAITING_SELLER_CODE":
            await self._handle_awaiting_seller_code(text, intent, supervisor, phone, chat_id, message_id, now)
            return

        if step == "AWAITING_RUTA_CODE":
            await self._handle_awaiting_ruta_code(text, intent, entry, supervisor, phone, chat_id, message_id, now)
            return

        # Unknown step (should not happen): treat it like a fresh conversation.
        await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)

    # --- Menus -------------------------------------------------------------

    async def _send_main_menu(
        self,
        phone: str,
        chat_id: str,
        fecha_trabajo,
        prefix: str = "",
        with_commands_hint: bool = False,
        keep_option: bool = False
    ) -> None:
        """
        Menu 1. Leaves the supervisor in AWAITING_MAIN_MENU so "1".."4" mean something.
        With keep_option (the supervisor already has a saved plan) it adds "5. Dejar mi
        planificación como está" and remembers it in the state: "5" then leaves the plan
        untouched, and a text the bot does not understand is no longer answered with the
        menu again (someone with a plan is not nagged to register).
        Known limitation (accepted): the day named in the menu is the target day at the
        moment it is sent; the plan itself is created with the target day at the moment
        of the answer. They differ only if the reply crosses a cutoff (Monday 15:00,
        Saturday 12:00).
        """
        self.conversation_svc.set(phone, "AWAITING_MAIN_MENU", payload={"keep_option": keep_option})
        text = (MSG_MAIN_MENU_KEEP if keep_option else MSG_MAIN_MENU).format(
            dia=weekday_name_es(fecha_trabajo), fecha=fecha_trabajo.strftime("%d/%m")
        )
        if with_commands_hint:
            text += f"\n\n{MSG_MAIN_MENU_COMMANDS_HINT}"
        if prefix:
            text = f"{prefix}\n\n{text}"
        await self.whatsapp_client.send_message(chat_id, text)

    async def _start_ruta_menu(self, phone: str, chat_id: str) -> None:
        """Menu 2. No sub-mode chosen yet: a first "1".."3" picks an option, a code still works as before."""
        self.conversation_svc.set(phone, "AWAITING_RUTA_CODE", payload={"list_shown": False, "submode": None})
        await self.whatsapp_client.send_message(chat_id, MSG_RUTA_MENU)

    async def _start_seller_code(self, phone: str, chat_id: str) -> None:
        self.conversation_svc.set(phone, "AWAITING_SELLER_CODE", payload={})
        await self.whatsapp_client.send_message(chat_id, MSG_ASK_SELLER_CODE)

    async def _handle_help(
        self,
        step: str,
        entry: Optional[Dict[str, Any]],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        fecha_trabajo
    ) -> None:
        """
        AYUDA. With nothing in progress it opens the main menu. In the middle of a
        flow it only REPEATS the current step: if it showed the main menu there, a
        "3" typed to answer it would be read by the step that is really waiting
        (e.g. as "Cancelar" in the confirmation) and could discard the plan.
        """
        payload = entry["payload"] if entry else {}
        if step == "AWAITING_CONFIRMATION":
            await self._resend_confirmation(payload["draft"], supervisor, chat_id)
        elif step == "AWAITING_SELECTION":
            await self.whatsapp_client.send_message(chat_id, build_selection_prompt(payload["candidates"]))
        elif step == "AWAITING_SELLER_CODE":
            await self.whatsapp_client.send_message(chat_id, MSG_ASK_SELLER_CODE)
        elif step == "AWAITING_RUTA_CODE":
            await self._resend_ruta_prompt(payload, chat_id)
        else:
            active = await run_in_sheets_thread(
                self.sheets_repo.find_active,
                fecha_trabajo.strftime("%Y-%m-%d"), supervisor["Sede"], supervisor["Nombre"]
            )
            await self._send_main_menu(
                phone, chat_id, fecha_trabajo,
                with_commands_hint=True, keep_option=is_real_planning(active)
            )

    async def _resend_ruta_prompt(self, payload: Dict[str, Any], chat_id: str) -> None:
        """Repeats whatever the RUTA flow is waiting for: the list, a code prompt or Menu 2."""
        routes = payload.get("routes") or []
        if payload.get("list_shown") and routes:
            fecha = datetime.strptime(payload["fecha_trabajo"], "%Y-%m-%d").date()
            message = build_route_list(fecha, routes, 1)
        elif payload.get("submode") == "seller":
            message = MSG_ASK_SELLER_CODE
        elif payload.get("submode") == "route":
            message = MSG_ASK_ROUTE_CODE
        else:
            message = MSG_RUTA_MENU
        await self.whatsapp_client.send_message(chat_id, message)

    async def _handle_correct(self, supervisor: Dict[str, Any], phone: str, chat_id: str, fecha_trabajo) -> None:
        """
        CORREGIR (Menu 4), from IDLE, the main menu or a pending confirmation: shows
        the SAVED plan (or says there is none) and goes back to the main menu to pick
        what to register. A pending draft is discarded: CORREGIR means "I want to
        change it".
        """
        fecha_str = fecha_trabajo.strftime("%Y-%m-%d")
        active = await run_in_sheets_thread(
            self.sheets_repo.find_active, fecha_str, supervisor["Sede"], supervisor["Nombre"]
        )
        if is_real_planning(active):
            saved_plan = await self._saved_plan_as_dict(active, fecha_str)
            prefix = build_current_plan_message(fecha_trabajo, get_weekday_code(fecha_trabajo), saved_plan)
        else:
            prefix = MSG_NO_PLAN_INFO.format(fecha=fecha_trabajo.strftime("%d/%m/%Y"))
        await self._send_main_menu(
            phone, chat_id, fecha_trabajo, prefix=prefix, keep_option=is_real_planning(active)
        )

    async def _resend_confirmation(self, draft: Dict[str, Any], supervisor: Dict[str, Any], chat_id: str) -> None:
        """Shows the pending summary (with its menu) again, without touching the state."""
        fecha_trabajo = datetime.strptime(draft["fecha_trabajo"], "%Y-%m-%d").date()
        active = await run_in_sheets_thread(
            self.sheets_repo.find_active, draft["fecha_trabajo"], supervisor["Sede"], supervisor["Nombre"]
        )
        build = build_confirmation_summary_update if is_real_planning(active) else build_confirmation_summary
        await self.whatsapp_client.send_message(
            chat_id, build(fecha_trabajo, get_weekday_code(fecha_trabajo), draft)
        )

    async def _handle_awaiting_main_menu(
        self,
        text: str,
        intent: Dict[str, Any],
        entry: Dict[str, Any],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        """
        Menu 1 answers. Any text command also works. Anything else repeats the menu,
        unless the supervisor already has a saved plan (keep_option): then the bot
        stays quiet instead of nagging, and "5" leaves the plan as it is.
        """
        keep_option = bool(entry["payload"].get("keep_option"))
        choice = parse_menu_choice(text)
        if choice == 5 and keep_option:
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_KEEP_PLAN_OK)
            return
        if choice == 1:
            await self._start_seller_code(phone, chat_id)
            return
        if choice == 2:
            await self._start_ruta_menu(phone, chat_id)
            return
        if choice == 3:
            intent = {"type": "venta_directa", "codigo_erp": None, "raw": text}
        elif choice == 4:
            intent = {"type": "oficina", "codigo_erp": None, "raw": text}

        if intent["type"] in ("code_only", "ruta", "venta_directa", "oficina"):
            await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)
            return
        if intent["type"] == "cancel":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return
        if intent["type"] == "correct":
            await self._handle_correct(supervisor, phone, chat_id, calculate_work_date(now))
            return
        if keep_option:
            return
        await self._send_main_menu(phone, chat_id, calculate_work_date(now))

    async def _handle_awaiting_seller_code(
        self,
        text: str,
        intent: Dict[str, Any],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        """
        Waiting for the code of the seller to accompany (main menu, option 1). Any
        number is a seller code here -- even "1" or "10": the supervisor already
        chose this sub-mode, so it is not a menu option. A rejected code keeps the
        state so another one can be tried.
        """
        ruta_input = extract_ruta_input(text)
        if ruta_input["type"] == "cancel":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return
        if intent["type"] in ("ruta", "venta_directa", "oficina"):
            await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)
            return
        if ruta_input["type"] == "number":
            await self._handle_seller_code(
                ruta_input["value"], MODALIDAD_ACOMPANAMIENTO, supervisor, phone, chat_id, message_id, now
            )
            return
        await self.whatsapp_client.send_message(chat_id, MSG_SELLER_CODE_INVALID)

    # --- New planning (code_only / ruta / venta_directa / oficina) ---

    async def _handle_new_planning(
        self,
        intent: Dict[str, Any],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        weekday_code = get_weekday_code(fecha_trabajo)

        if intent["type"] == "code_only":
            await self._handle_seller_code(
                intent["codigo_erp"], MODALIDAD_ACOMPANAMIENTO,
                supervisor, phone, chat_id, message_id, now
            )
            return

        if intent["type"] == "ruta":
            await self._start_ruta_menu(phone, chat_id)
            return

        if intent["type"] == "venta_directa":
            plan = self._build_plan_dict(
                modalidad="VENTA DIRECTA",
                vendedor_apoyo="VENTA DIRECTA",
                codigo_erp_vendedor="N/A",
                route_row=None,
                fecha_trabajo=fecha_trabajo_str,
                sede=sede,
                supervisor=supervisor_name
            )
            await self._propose_for_confirmation(plan, chat_id, phone, fecha_trabajo, weekday_code, sede, supervisor_name)
            return

        if intent["type"] == "oficina":
            plan = self._build_plan_dict(
                modalidad="OFICINA",
                vendedor_apoyo="N/A",
                codigo_erp_vendedor="N/A",
                route_row=None,
                fecha_trabajo=fecha_trabajo_str,
                sede=sede,
                supervisor=supervisor_name
            )
            await self._propose_for_confirmation(plan, chat_id, phone, fecha_trabajo, weekday_code, sede, supervisor_name)
            return

        # unknown / confirm / cancel with nothing pending (and no saved plan): offer the main menu.
        await self._send_main_menu(phone, chat_id, fecha_trabajo)

    async def _handle_seller_code(
        self,
        codigo_erp: str,
        modalidad: str,
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        """
        Seller-code planning shared by ACOMPAÑAMIENTO (code alone) and RUTA
        (seller code sent while in AWAITING_RUTA_CODE): zone check, today's route(s), duplicate
        check, then a confirmation proposal (or route selection if several).
        Only the modalidad differs between the two.
        """
        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]
        fecha_trabajo = calculate_work_date(now)
        fecha_trabajo_str = fecha_trabajo.strftime("%Y-%m-%d")
        weekday_code = get_weekday_code(fecha_trabajo)

        # Validación de zona del supervisor
        zona = supervisor.get("Zona")
        if not zona or not str(zona).strip():
            await self.whatsapp_client.send_message(chat_id, MSG_SUPERVISOR_NO_ZONE)
            await run_in_sheets_thread(
                self.audit_svc.log,
                phone=phone,
                whatsapp_id=chat_id,
                supervisor=supervisor_name,
                sede=sede,
                whatsapp_message_id=message_id,
                original_message=str(codigo_erp),
                action="REJECTED_NO_ZONE",
                result="REJECTED",
                details="Supervisor no tiene zona asignada en hoja SUPERVISORES"
            )
            return

        supervisor_zona = str(zona).strip()
        seller_rows = await run_in_sheets_thread(
            self.masters_service.get_seller_by_code_and_zone,
            sede, codigo_erp, supervisor_zona
        )
        if not seller_rows:
            other_seller_rows = await run_in_sheets_thread(self.masters_service.get_seller_by_code, sede, codigo_erp)
            if other_seller_rows:
                first_other = other_seller_rows[0]
                vendedor_name = first_other.get("VENDEDOR", "")
                zona_vendedor = first_other.get("ZONA", "")
                msg = MSG_SELLER_WRONG_ZONE.format(
                    codigo=codigo_erp,
                    vendedor=vendedor_name,
                    zona_vendedor=zona_vendedor
                )
                await self.whatsapp_client.send_message(chat_id, msg)
                await run_in_sheets_thread(
                    self.audit_svc.log,
                    phone=phone,
                    whatsapp_id=chat_id,
                    supervisor=supervisor_name,
                    sede=sede,
                    whatsapp_message_id=message_id,
                    original_message=str(codigo_erp),
                    action="REJECTED_WRONG_ZONE",
                    result="REJECTED",
                    details=f"Vendedor pertenece a zona {zona_vendedor}, supervisor tiene {supervisor_zona}"
                )
                return
            else:
                await self.whatsapp_client.send_message(chat_id, MSG_SELLER_CODE_NOT_FOUND)
                return

        routes = [r for r in seller_rows if str(r.get("DIA", "")).strip() == weekday_code]
        if not routes:
            await self.whatsapp_client.send_message(chat_id, MSG_SELLER_NO_ROUTE_TODAY)
            return

        seller_row = seller_rows[0]

        # Prevenir doble registro del mismo vendedor el mismo día
        duplicate = await run_in_sheets_thread(
            self.sheets_repo.find_seller_duplicate,
            fecha_trabajo_str, codigo_erp, supervisor_name, sede
        )
        if duplicate is not None:
            otro_supervisor = duplicate.get("Supervisor", "")
            # RUTA rows have an empty Vendedor_Apoyo -> use the master's name.
            vendedor_nombre = duplicate.get("Vendedor_Apoyo") or seller_row.get("VENDEDOR", "")
            msg = MSG_SELLER_ALREADY_ASSIGNED.format(
                vendedor=vendedor_nombre,
                fecha=fecha_trabajo.strftime("%d/%m/%Y"),
                otro_supervisor=otro_supervisor
            )
            await self.whatsapp_client.send_message(chat_id, msg)
            await run_in_sheets_thread(
                self.audit_svc.log,
                phone=phone,
                whatsapp_id=chat_id,
                supervisor=supervisor_name,
                sede=sede,
                whatsapp_message_id=message_id,
                original_message=str(codigo_erp),
                action="REJECTED_DUPLICATE_SELLER",
                result="REJECTED",
                details=f"Vendedor ya registrado por {otro_supervisor}"
            )
            return

        if len(routes) == 1:
            plan = self._build_seller_plan(
                modalidad, seller_row, codigo_erp, routes[0],
                fecha_trabajo_str, sede, supervisor_name
            )
            await self._propose_for_confirmation(plan, chat_id, phone, fecha_trabajo, weekday_code, sede, supervisor_name)
            return

        self.conversation_svc.set(phone, "AWAITING_SELECTION", payload={
            "candidates": routes,
            "seller_row": seller_row,
            "codigo_erp": codigo_erp,
            "modalidad": modalidad,
            "fecha_trabajo": fecha_trabajo_str,
            "attempts": 0
        })
        await self.whatsapp_client.send_message(chat_id, build_selection_prompt(routes))
        return

    def _build_seller_plan(
        self,
        modalidad: str,
        seller_row: Dict[str, Any],
        codigo_erp: str,
        route_row: Dict[str, Any],
        fecha_trabajo: str,
        sede: str,
        supervisor: str
    ) -> Dict[str, Any]:
        """
        Plan for a seller-code planning. ACOMPAÑAMIENTO records the seller as
        Vendedor_Apoyo; RUTA (supervisor covers the route alone) records an
        empty string there and keeps the seller's name in `vendedor_nombre`,
        which is only used for the confirmation summary and never written to
        the Sheet.
        """
        seller_name = seller_row.get("VENDEDOR", "")
        plan = self._build_plan_dict(
            modalidad=modalidad,
            # TEMPORARY: RUTA stores "" in Vendedor_Apoyo (the supervisor goes
            # alone, there is no supporting seller), while OFICINA and
            # VENTA DIRECTA still store "N/A". The inconsistency is deliberate
            # for now; unify the "no value" convention in a future refactor.
            vendedor_apoyo="" if modalidad == MODALIDAD_RUTA else seller_name,
            codigo_erp_vendedor=codigo_erp,
            route_row=route_row,
            fecha_trabajo=fecha_trabajo,
            sede=sede,
            supervisor=supervisor
        )
        if modalidad == MODALIDAD_RUTA:
            plan["vendedor_nombre"] = seller_name
        return plan

    def _build_route_plan(
        self,
        route_row: Dict[str, Any],
        fecha_trabajo: str,
        sede: str,
        supervisor: str
    ) -> Dict[str, Any]:
        """
        RUTA plan for a route picked directly (from LISTA or by route code):
        no seller ERP code ('N/A'), empty Vendedor_Apoyo. The route's seller
        name, if any, is kept in `vendedor_nombre` for the summary only.
        """
        plan = self._build_plan_dict(
            modalidad=MODALIDAD_RUTA,
            vendedor_apoyo="",
            codigo_erp_vendedor="N/A",
            route_row=route_row,
            fecha_trabajo=fecha_trabajo,
            sede=sede,
            supervisor=supervisor
        )
        plan["vendedor_nombre"] = str(route_row.get("VENDEDOR", "") or "").strip()
        return plan

    def _build_plan_dict(
        self,
        modalidad: str,
        vendedor_apoyo: str,
        codigo_erp_vendedor: str,
        route_row: Optional[Dict[str, Any]],
        fecha_trabajo: str,
        sede: str,
        supervisor: str
    ) -> Dict[str, Any]:
        if route_row:
            ruta_oficial = route_row.get("RUTA", "N/A")
            zona = route_row.get("ZONA", "N/A")
            codigo_ruta = route_row.get("CODIGO RUTA", "N/A")
            dia = route_row.get("DIA", "N/A")
        else:
            ruta_oficial = zona = codigo_ruta = dia = "N/A"

        return {
            "modalidad": modalidad,
            "vendedor_apoyo": vendedor_apoyo,
            "codigo_erp_vendedor": codigo_erp_vendedor,
            "ruta_oficial": ruta_oficial,
            "zona": zona,
            "codigo_ruta": codigo_ruta,
            "dia": dia,
            "fecha_trabajo": fecha_trabajo,
            "sede": sede,
            "supervisor": supervisor
        }

    @staticmethod
    def _sheet_content(plan: Dict[str, Any]) -> Dict[str, Any]:
        """The PLANIFICACION_DIARIA columns that define a plan's content (what same_planning compares)."""
        return {
            "Modalidad": plan["modalidad"],
            "Vendedor_Apoyo": plan["vendedor_apoyo"],
            "Codigo_ERP_Vendedor": plan["codigo_erp_vendedor"],
            "Ruta_Oficial": plan["ruta_oficial"],
            "Zona": plan["zona"],
            "Codigo_Ruta": plan["codigo_ruta"],
            "DIA": plan["dia"],
        }

    async def _saved_plan_as_dict(self, row: Dict[str, Any], fecha_trabajo: str) -> Dict[str, Any]:
        """Turns a saved PLANIFICACION_DIARIA row back into the plan dict the summaries expect."""
        plan = {
            "modalidad": str(row.get("Modalidad", "")),
            "vendedor_apoyo": str(row.get("Vendedor_Apoyo", "")),
            "codigo_erp_vendedor": str(row.get("Codigo_ERP_Vendedor", "")),
            "ruta_oficial": str(row.get("Ruta_Oficial", "")),
            "zona": str(row.get("Zona", "")),
            "codigo_ruta": str(row.get("Codigo_Ruta", "")),
            "dia": str(row.get("DIA", "")),
            "fecha_trabajo": fecha_trabajo,
            "sede": str(row.get("Sede", "")),
            "supervisor": str(row.get("Supervisor", "")),
        }
        if plan["modalidad"] == MODALIDAD_RUTA:
            # The sheet row keeps no seller name for RUTA (Vendedor_Apoyo is empty):
            # take it from the masters, by route code, for the summary only.
            route = await run_in_sheets_thread(
                self.masters_service.get_route_by_code,
                plan["sede"], plan["zona"], plan["dia"], plan["codigo_ruta"]
            )
            plan["vendedor_nombre"] = str((route or {}).get("VENDEDOR", "") or "").strip()
        return plan

    async def _propose_for_confirmation(
        self,
        plan: Dict[str, Any],
        chat_id: str,
        phone: str,
        fecha_trabajo,
        weekday_code: str,
        sede: str,
        supervisor_name: str
    ) -> None:
        active = await run_in_sheets_thread(self.sheets_repo.find_active, plan["fecha_trabajo"], sede, supervisor_name)

        if same_planning(active, self._sheet_content(plan)):
            # Same content as the saved plan: no confirmation, no "replace" warning.
            # Any older pending draft is superseded by this (identical) request.
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_PLAN_ALREADY_ACTIVE)
            return

        self.conversation_svc.set(phone, "AWAITING_CONFIRMATION", payload={"draft": plan})

        if is_real_planning(active):
            summary = build_confirmation_summary_update(fecha_trabajo, weekday_code, plan)
        else:
            summary = build_confirmation_summary(fecha_trabajo, weekday_code, plan)
        await self.whatsapp_client.send_message(chat_id, summary)

    # --- AWAITING_CONFIRMATION ---

    async def _handle_awaiting_confirmation(
        self,
        intent: Dict[str, Any],
        entry: Dict[str, Any],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        draft = entry["payload"]["draft"]
        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]

        if intent["type"] == "confirm":
            sheet_payload = {**self._sheet_content(draft), "ID_Mensaje_WA": message_id}
            result = await run_in_sheets_thread(
                self.sheets_repo.upsert,
                draft["fecha_trabajo"], sede, supervisor_name, sheet_payload,
                skip_if_unchanged=True
            )

            if result.get("__unchanged"):
                # The saved plan already has exactly this content: nothing was written.
                self.conversation_svc.clear(phone)
                await self.whatsapp_client.send_message(chat_id, MSG_PLAN_ALREADY_ACTIVE)
                await run_in_sheets_thread(
                    self.audit_svc.log,
                    phone=phone,
                    whatsapp_id=chat_id,
                    supervisor=supervisor_name,
                    sede=sede,
                    whatsapp_message_id=message_id,
                    action="CONFIRM_PLANNING",
                    state_after=result.get("Estado"),
                    result="NO_CHANGES",
                    details=f"Plan identico al activo; no se escribio en el Sheet (row id: {result.get('ID_Registro')})"
                )
                return

            is_mod = result.get("Es_Cambio") == "TRUE"

            self.conversation_svc.clear(phone)
            ack = MSG_UPDATED_OK if is_mod else MSG_REGISTERED_OK
            await self.whatsapp_client.send_message(chat_id, ack)

            await run_in_sheets_thread(
                self.audit_svc.log,
                phone=phone,
                whatsapp_id=chat_id,
                supervisor=supervisor_name,
                sede=sede,
                whatsapp_message_id=message_id,
                action="CONFIRM_PLANNING",
                state_after="MODIFICADO" if is_mod else "REGISTRADO",
                result="SUCCESS",
                details=f"Sheet row id: {result.get('ID_Registro')}"
            )
            return

        if intent["type"] == "correct":
            # Menu 4: show what is SAVED (not the draft the supervisor just saw) and go
            # back to the main menu; the pending draft is discarded.
            fecha_trabajo_date = datetime.strptime(draft["fecha_trabajo"], "%Y-%m-%d").date()
            await self._handle_correct(supervisor, phone, chat_id, fecha_trabajo_date)
            return

        if intent["type"] == "cancel":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return

        if intent["type"] in ("code_only", "ruta", "venta_directa", "oficina"):
            # A fresh planning submission overwrites the pending draft.
            await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)
            return

        # Anything else: repeat the summary with its menu.
        await self._resend_confirmation(draft, supervisor, chat_id)

    # --- AWAITING_SELECTION ---

    async def _handle_awaiting_selection(
        self,
        text: str,
        entry: Dict[str, Any],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str
    ) -> None:
        payload = entry["payload"]
        candidates = payload["candidates"]
        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]

        # Same normalization as every other command; only the word "cancelar" and
        # plain numbers are recognized in this step.
        if normalize_command(text) == "cancelar":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return

        selected_index = None
        number = parse_number(text)
        if number is not None:
            idx = int(number)
            if 1 <= idx <= len(candidates):
                selected_index = idx - 1

        if selected_index is None:
            attempts = payload.get("attempts", 0) + 1
            if attempts >= MAX_SELECTION_ATTEMPTS:
                self.conversation_svc.clear(phone)
                await self.whatsapp_client.send_message(chat_id, MSG_SELECTION_TOO_MANY_ERRORS)
                return
            payload["attempts"] = attempts
            self.conversation_svc.set(phone, "AWAITING_SELECTION", payload=payload)
            await self.whatsapp_client.send_message(chat_id, MSG_SELECTION_INVALID)
            return

        route_row = candidates[selected_index]
        seller_row = payload["seller_row"]
        fecha_trabajo_str = payload["fecha_trabajo"]
        fecha_trabajo_date = datetime.strptime(fecha_trabajo_str, "%Y-%m-%d").date()
        weekday_code = get_weekday_code(fecha_trabajo_date)

        plan = self._build_seller_plan(
            payload.get("modalidad", MODALIDAD_ACOMPANAMIENTO), seller_row,
            payload["codigo_erp"], route_row, fecha_trabajo_str, sede, supervisor_name
        )
        await self._propose_for_confirmation(plan, chat_id, phone, fecha_trabajo_date, weekday_code, sede, supervisor_name)

    # --- AWAITING_RUTA_CODE ---

    async def _handle_awaiting_ruta_code(
        self,
        text: str,
        intent: Dict[str, Any],
        entry: Dict[str, Any],
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        """
        The RUTA flow. What a number means depends on where the supervisor is:
        - Menu 2 on screen, no sub-mode yet: exactly "1" / "2" / "3" pick an option
          (by seller code / by route code / LISTA); a number with 2+ digits is a code,
          looked up as before (seller first, then route), so "RUTA" then "10" works.
        - Sub-mode "seller" / "route" (an option was chosen): ANY number is a code of
          that kind, never a menu option.
        - LISTA on screen: a number up to the size of the list is a position in it.
        Also valid at any point: LISTA [page], CANCELAR, and the commands RUTA /
        VENTA DIRECTA / OFICINA. Rejections keep the state so another attempt is possible.
        """
        payload = entry["payload"]
        submode = payload.get("submode")
        ruta_input = extract_ruta_input(text)

        if ruta_input["type"] == "cancel":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return

        if intent["type"] in ("ruta", "venta_directa", "oficina"):
            await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)
            return

        if ruta_input["type"] == "lista":
            await self._show_route_list(ruta_input["page"], supervisor, phone, chat_id, now)
            return

        routes = payload.get("routes") or []
        list_shown = bool(payload.get("list_shown") and routes)

        if ruta_input["type"] != "number":
            # Not a command and not a number: repeat only the step the supervisor is on.
            if list_shown:
                message = MSG_LIST_PICK_INVALID
            elif submode == "seller":
                message = MSG_SELLER_CODE_INVALID
            elif submode == "route":
                message = MSG_ROUTE_CODE_INVALID
            else:
                message = MSG_RUTA_MENU
            await self.whatsapp_client.send_message(chat_id, message)
            return

        value = ruta_input["value"]

        if list_shown:
            # With the list on screen a number is first of all a position in it.
            # (If a route code collides with a position, the position wins: the
            # list itself says "send the NUMBER".)
            position = int(value)
            if 1 <= position <= len(routes):
                fecha_trabajo_date = datetime.strptime(payload["fecha_trabajo"], "%Y-%m-%d").date()
                await self._propose_route(routes[position - 1], fecha_trabajo_date, supervisor, phone, chat_id)
                return
            if len(value) == 1:
                await self.whatsapp_client.send_message(
                    chat_id, MSG_RUTA_LIST_OUT_OF_RANGE.format(total=len(routes))
                )
                return
            # 2+ digits beyond the list: maybe a code typed instead of a position. If it is
            # not a code either and it is short, it was a mistyped position.
            await self._handle_ruta_code(
                value, "any", supervisor, phone, chat_id, message_id, now,
                not_found_message=MSG_RUTA_LIST_OUT_OF_RANGE.format(total=len(routes)) if len(value) <= 2 else None
            )
            return

        if submode == "seller":
            await self._handle_seller_code(value, MODALIDAD_RUTA, supervisor, phone, chat_id, message_id, now)
            return
        if submode == "route":
            await self._handle_ruta_code(value, "route", supervisor, phone, chat_id, message_id, now)
            return

        # Menu 2 on screen, nothing chosen yet.
        if value == "1":
            self.conversation_svc.set(phone, "AWAITING_RUTA_CODE", payload={"list_shown": False, "submode": "seller"})
            await self.whatsapp_client.send_message(chat_id, MSG_ASK_SELLER_CODE)
            return
        if value == "2":
            self.conversation_svc.set(phone, "AWAITING_RUTA_CODE", payload={"list_shown": False, "submode": "route"})
            await self.whatsapp_client.send_message(chat_id, MSG_ASK_ROUTE_CODE)
            return
        if value == "3":
            await self._show_route_list(1, supervisor, phone, chat_id, now)
            return
        if len(value) == 1:
            await self.whatsapp_client.send_message(chat_id, MSG_RUTA_MENU)  # 0, 4..9: not an option
            return

        await self._handle_ruta_code(value, "any", supervisor, phone, chat_id, message_id, now)

    async def _handle_ruta_code(
        self,
        code: str,
        mode: str,
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime,
        not_found_message: Optional[str] = None
    ) -> None:
        """
        A code sent in the RUTA flow.
        - mode "any": seller code first (same flow and validations as a plain seller
          code, but modalidad RUTA); if no seller in the supervisor's zone has it, a
          route code of the supervisor's zone and day.
        - mode "route": only a route code of the supervisor's zone and day.
        `not_found_message` replaces the final "not found" answer (the LISTA flow uses
        it to say "out of range" for short numbers).
        """
        sede = supervisor["Sede"]
        zona = str(supervisor.get("Zona") or "").strip()
        if not zona:
            # _handle_seller_code answers with the "no zone assigned" message.
            await self._handle_seller_code(
                code, MODALIDAD_RUTA, supervisor, phone, chat_id, message_id, now
            )
            return

        if mode == "any" and await run_in_sheets_thread(
            self.masters_service.get_seller_by_code_and_zone, sede, code, zona
        ):
            await self._handle_seller_code(
                code, MODALIDAD_RUTA, supervisor, phone, chat_id, message_id, now
            )
            return

        fecha_trabajo = calculate_work_date(now)
        route_row = await run_in_sheets_thread(
            self.masters_service.get_route_by_code,
            sede, zona, get_weekday_code(fecha_trabajo), code
        )
        if route_row:
            await self._propose_route(route_row, fecha_trabajo, supervisor, phone, chat_id)
            return

        if mode == "route":
            await self.whatsapp_client.send_message(chat_id, not_found_message or MSG_ROUTE_CODE_NOT_FOUND)
            return

        if await run_in_sheets_thread(self.masters_service.get_seller_by_code, sede, code):
            # The seller exists but in another zone: same "wrong zone" answer as always.
            await self._handle_seller_code(
                code, MODALIDAD_RUTA, supervisor, phone, chat_id, message_id, now
            )
            return

        await self.whatsapp_client.send_message(chat_id, not_found_message or MSG_RUTA_CODE_NOT_FOUND)

    async def _show_route_list(
        self,
        page: int,
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        now: datetime
    ) -> None:
        """Sends one page of the day's routes for the supervisor's zone and keeps AWAITING_RUTA_CODE."""
        zona = str(supervisor.get("Zona") or "").strip()
        if not zona:
            await self.whatsapp_client.send_message(chat_id, MSG_SUPERVISOR_NO_ZONE)
            return

        fecha_trabajo = calculate_work_date(now)
        weekday_code = get_weekday_code(fecha_trabajo)
        routes = await run_in_sheets_thread(self.masters_service.get_routes_by_zone_and_day, supervisor["Sede"], zona, weekday_code)
        if not routes:
            await self.whatsapp_client.send_message(
                chat_id,
                MSG_RUTA_LIST_EMPTY.format(dia=f"{fecha_trabajo.strftime('%d/%m/%Y')} ({weekday_code})")
            )
            return

        pages = route_list_pages(len(routes))
        if not 1 <= page <= pages:
            await self.whatsapp_client.send_message(chat_id, MSG_RUTA_LIST_BAD_PAGE.format(pages=pages))
            return

        self.conversation_svc.set(phone, "AWAITING_RUTA_CODE", payload={
            "list_shown": True,
            "submode": None,
            "routes": routes,
            "fecha_trabajo": fecha_trabajo.strftime("%Y-%m-%d")
        })
        await self.whatsapp_client.send_message(chat_id, build_route_list(fecha_trabajo, routes, page))

    async def _propose_route(
        self,
        route_row: Dict[str, Any],
        fecha_trabajo,
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str
    ) -> None:
        # 1 supervisor per zone per sede -> no duplicate check between
        # supervisors is needed in the RUTA flow when a route is picked directly
        # (LISTA or route code). The zone validation already restricts the
        # routes a supervisor can see. (Picking by seller code keeps the
        # seller duplicate check in _handle_seller_code.)
        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]
        plan = self._build_route_plan(
            route_row, fecha_trabajo.strftime("%Y-%m-%d"), sede, supervisor_name
        )
        await self._propose_for_confirmation(
            plan, chat_id, phone, fecha_trabajo, get_weekday_code(fecha_trabajo), sede, supervisor_name
        )
