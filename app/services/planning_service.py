"""
Core planning orchestrator service.

Flow (see PARTE 6 of the spec): resolve sender phone -> authenticate ->
AYUDA -> conversational state (AWAITING_CONFIRMATION / AWAITING_SELECTION /
AWAITING_VENTA_CODE) -> day/window check -> new planning (seller code,
VENTA, VENTA DIRECTA, OFICINA).

Silence policy: unresolvable senders and unauthorized phones get ZERO trace
(no reply, no LOG_BOT). Authenticated supervisors always get an audit trail,
even when ignored for being outside the planning window.
"""
import logging
from typing import Any, Dict, Optional
from datetime import datetime, time

from app.config import get_settings
from app.business.dates import calculate_work_date, get_weekday_code, get_current_bolivia_datetime
from app.business.planning_rules import (
    build_confirmation_summary,
    build_confirmation_summary_update,
    build_selection_prompt
)
from app.whatsapp.parser import ParsedWhatsAppMessage, extract_planning_intent
from app.whatsapp.lid_resolver import resolve_to_phone
from app.whatsapp.templates import (
    MSG_HELP,
    MSG_SELLER_CODE_NOT_FOUND,
    MSG_SELLER_NO_ROUTE_TODAY,
    MSG_SUPERVISOR_NO_ZONE,
    MSG_SELLER_WRONG_ZONE,
    MSG_SELLER_ALREADY_ASSIGNED,
    MSG_REGISTERED_OK,
    MSG_UPDATED_OK,
    MSG_AWAITING_CONFIRMATION_HELP,
    MSG_CORRECT_REQUESTED,
    MSG_CANCELLED_NO_CHANGES,
    MSG_SELECTION_INVALID,
    MSG_SELECTION_TOO_MANY_ERRORS,
    MSG_VENTA_ASK_CODE,
    MSG_VENTA_CODE_INVALID
)
from app.whatsapp.client import WhatsAppClient
from app.sheets.masters import MastersService
from app.sheets.planning_repository import GoogleSheetsPlanningRepository
from app.services.supervisor_service import SupervisorService
from app.services.conversation_service import ConversationService
from app.services.audit_service import AuditService

MAX_SELECTION_ATTEMPTS = 3

MODALIDAD_ACOMPANAMIENTO = "ACOMPAÑAMIENTO"
MODALIDAD_VENTA = "VENTA"

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
        self.settings = get_settings()
        self.supervisor_svc = supervisor_service or SupervisorService()
        self.conversation_svc = conversation_service or ConversationService()
        self.audit_svc = audit_service or AuditService()

        self.whatsapp_client = whatsapp_client or WhatsAppClient()
        self.sheets_repo = sheets_repo or GoogleSheetsPlanningRepository()
        self.masters_service = masters_service or MastersService()

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
        supervisor = self.supervisor_svc.authenticate(phone)
        if not supervisor:
            return

        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]

        # 3. AYUDA/HELP is always available, in any conversational state.
        intent = extract_planning_intent(text)
        if intent["type"] == "help":
            await self.whatsapp_client.send_message(chat_id, MSG_HELP)
            return

        # 4. Conversational state (in-memory, keyed by phone).
        now = eval_datetime or get_current_bolivia_datetime()
        entry = self.conversation_svc.get(phone)
        step = entry["state"] if entry else "IDLE"

        # Silencio después de registrado: si ya tiene plan activo para la fecha y está en IDLE
        fecha_trabajo = calculate_work_date(now)
        active = self.sheets_repo.find_active(
            fecha_trabajo.strftime("%Y-%m-%d"),
            sede, supervisor_name
        )
        if active is not None and step == "IDLE":
            if intent["type"] in ("unknown", "confirm", "correct"):
                self.audit_svc.log(
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

        if step == "AWAITING_CONFIRMATION":
            await self._handle_awaiting_confirmation(intent, entry, supervisor, phone, chat_id, message_id, now)
            return

        if step == "AWAITING_SELECTION":
            await self._handle_awaiting_selection(text, entry, supervisor, phone, chat_id)
            return

        if step == "AWAITING_VENTA_CODE":
            await self._handle_awaiting_venta_code(text, supervisor, phone, chat_id, message_id, now)
            return

        # 5. IDLE: day/window check.
        weekday = now.weekday()  # 0=Monday ... 6=Sunday
        if weekday == 6 or weekday == 5 or not self._is_within_planning_window(now):
            self.audit_svc.log(
                phone=phone,
                whatsapp_id=chat_id,
                supervisor=supervisor_name,
                sede=sede,
                whatsapp_message_id=message_id,
                original_message=text,
                action="OUTSIDE_WINDOW",
                result="IGNORED",
                details="Mensaje ignorado: fuera de la ventana de planificación"
            )
            return

        # 6. New planning.
        await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)

    # --- New planning (code_only / venta / venta_directa / oficina) ---

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

        if intent["type"] == "venta":
            # Ask which seller's route will be covered; the code arrives next.
            self.conversation_svc.set(phone, "AWAITING_VENTA_CODE")
            await self.whatsapp_client.send_message(chat_id, MSG_VENTA_ASK_CODE)
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

        # unknown / confirm / correct / cancel with nothing pending: just help.
        await self.whatsapp_client.send_message(chat_id, MSG_HELP)

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
        Seller-code planning shared by ACOMPAÑAMIENTO (code alone) and VENTA
        (code sent after 'venta'): zone check, today's route(s), duplicate
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
            self.audit_svc.log(
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
        seller_rows = self.masters_service.get_seller_by_code_and_zone(
            sede, codigo_erp, supervisor_zona
        )
        if not seller_rows:
            other_seller_rows = self.masters_service.get_seller_by_code(sede, codigo_erp)
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
                self.audit_svc.log(
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
        duplicate = self.sheets_repo.find_seller_duplicate(
            fecha_trabajo_str, codigo_erp, supervisor_name, sede
        )
        if duplicate is not None:
            otro_supervisor = duplicate.get("Supervisor", "")
            # VENTA rows have an empty Vendedor_Apoyo -> use the master's name.
            vendedor_nombre = duplicate.get("Vendedor_Apoyo") or seller_row.get("VENDEDOR", "")
            msg = MSG_SELLER_ALREADY_ASSIGNED.format(
                vendedor=vendedor_nombre,
                fecha=fecha_trabajo.strftime("%d/%m/%Y"),
                otro_supervisor=otro_supervisor
            )
            await self.whatsapp_client.send_message(chat_id, msg)
            self.audit_svc.log(
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
        Vendedor_Apoyo; VENTA (supervisor covers the route alone) records an
        empty string there and keeps the seller's name in `vendedor_nombre`,
        which is only used for the confirmation summary and never written to
        the Sheet.
        """
        seller_name = seller_row.get("VENDEDOR", "")
        plan = self._build_plan_dict(
            modalidad=modalidad,
            # TEMPORARY: VENTA stores "" in Vendedor_Apoyo (the supervisor goes
            # alone, there is no supporting seller), while OFICINA and
            # VENTA DIRECTA still store "N/A". The inconsistency is deliberate
            # for now; unify the "no value" convention in a future refactor.
            vendedor_apoyo="" if modalidad == MODALIDAD_VENTA else seller_name,
            codigo_erp_vendedor=codigo_erp,
            route_row=route_row,
            fecha_trabajo=fecha_trabajo,
            sede=sede,
            supervisor=supervisor
        )
        if modalidad == MODALIDAD_VENTA:
            plan["vendedor_nombre"] = seller_name
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
        active = self.sheets_repo.find_active(plan["fecha_trabajo"], sede, supervisor_name)
        self.conversation_svc.set(phone, "AWAITING_CONFIRMATION", payload={"draft": plan})

        if active:
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
            sheet_payload = {
                "Modalidad": draft["modalidad"],
                "Vendedor_Apoyo": draft["vendedor_apoyo"],
                "Codigo_ERP_Vendedor": draft["codigo_erp_vendedor"],
                "Ruta_Oficial": draft["ruta_oficial"],
                "Zona": draft["zona"],
                "Codigo_Ruta": draft["codigo_ruta"],
                "DIA": draft["dia"],
                "ID_Mensaje_WA": message_id
            }
            result = self.sheets_repo.upsert(draft["fecha_trabajo"], sede, supervisor_name, sheet_payload)
            is_mod = result.get("Es_Cambio") == "TRUE"

            self.conversation_svc.clear(phone)
            ack = MSG_UPDATED_OK if is_mod else MSG_REGISTERED_OK
            await self.whatsapp_client.send_message(chat_id, ack)

            self.audit_svc.log(
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
            fecha_trabajo_date = datetime.strptime(draft["fecha_trabajo"], "%Y-%m-%d").date()
            weekday_code = get_weekday_code(fecha_trabajo_date)
            summary = build_confirmation_summary(fecha_trabajo_date, weekday_code, draft)
            await self.whatsapp_client.send_message(chat_id, f"{summary}\n\n{MSG_CORRECT_REQUESTED}")
            # Keep AWAITING_CONFIRMATION with the same draft — nothing else to do.
            return

        if intent["type"] == "cancel":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return

        if intent["type"] in ("code_only", "venta", "venta_directa", "oficina"):
            # A fresh planning submission overwrites the pending draft.
            await self._handle_new_planning(intent, supervisor, phone, chat_id, message_id, now)
            return

        await self.whatsapp_client.send_message(chat_id, MSG_AWAITING_CONFIRMATION_HELP)

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
        upper = text.strip().upper()
        sede = supervisor["Sede"]
        supervisor_name = supervisor["Nombre"]

        if upper == "CANCELAR":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return

        selected_index = None
        if upper.isdigit():
            idx = int(upper)
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

    # --- AWAITING_VENTA_CODE ---

    async def _handle_awaiting_venta_code(
        self,
        text: str,
        supervisor: Dict[str, Any],
        phone: str,
        chat_id: str,
        message_id: str,
        now: datetime
    ) -> None:
        intent = extract_planning_intent(text)

        if intent["type"] == "cancel":
            self.conversation_svc.clear(phone)
            await self.whatsapp_client.send_message(chat_id, MSG_CANCELLED_NO_CHANGES)
            return

        if intent["type"] != "code_only":
            await self.whatsapp_client.send_message(chat_id, MSG_VENTA_CODE_INVALID)
            return

        # Same validations as a plain seller code; a rejection leaves the
        # state in AWAITING_VENTA_CODE so the supervisor can retry another code.
        await self._handle_seller_code(
            intent["codigo_erp"], MODALIDAD_VENTA,
            supervisor, phone, chat_id, message_id, now
        )

    # --- helpers ---

    def _is_within_planning_window(self, now: datetime) -> bool:
        """True if `now` falls within [PLANNING_WINDOW_START, PLANNING_WINDOW_END] (America/La_Paz)."""
        start_hour, start_minute = map(int, self.settings.PLANNING_WINDOW_START.split(":"))
        end_hour, end_minute = map(int, self.settings.PLANNING_WINDOW_END.split(":"))
        window_start = time(start_hour, start_minute)
        window_end = time(end_hour, end_minute)
        return window_start <= now.time() <= window_end
