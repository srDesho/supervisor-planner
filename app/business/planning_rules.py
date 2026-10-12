"""
High-level planning domain rules and proposal generators.
Formats the confirmation summary, the update warning, the route-selection
prompt and rejection messages shown to the supervisor.
"""
from typing import Any, Dict, List, Optional
from datetime import date

_WEEKDAY_NAMES_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}


def _seller_name(raw: Any) -> str:
    """The seller's name, or '' when the master row has none (blank / 'N/A')."""
    name = str(raw or "").strip()
    return "" if name.upper() == "N/A" else name


def build_plan_details(fecha_trabajo: date, weekday_code: str, plan: Dict[str, Any]) -> str:
    """
    The fields of a plan, formatted for its modality (no header, no question):
    - OFICINA / VENTA DIRECTA: minimal (no seller, route or zone to show).
    - RUTA: modality line + route + (optional) seller name, no ERP/zone.
    - ACOMPAÑAMIENTO: the full list.
    Shared by the confirmation summary and by "your current plan is...".
    """
    nombre_dia = _WEEKDAY_NAMES_ES[fecha_trabajo.weekday()]
    modalidad = plan.get("modalidad")
    if modalidad in ("OFICINA", "VENTA DIRECTA"):
        return (
            f"🏢 Modalidad: {modalidad}\n"
            f"📆 Fecha: {fecha_trabajo.strftime('%d/%m/%Y')} ({nombre_dia} - {weekday_code})\n"
            f"🏢 Sede: {plan.get('sede', 'N/A')}\n"
            f"👤 Supervisor: {plan.get('supervisor', 'N/A')}"
        )
    if modalidad == "RUTA":
        # Vendedor_Apoyo is empty for RUTA (see _build_route_plan), so no
        # "Vendedor:" label; show the route's seller name, if it has one.
        seller = _seller_name(plan.get("vendedor_nombre"))
        seller_line = f"👤 {seller}\n" if seller else ""
        return (
            "🚗 Modalidad: RUTA (cubres la ruta solo)\n"
            f"🗺️ Ruta: {plan.get('ruta_oficial', 'N/A')}\n"
            f"{seller_line}"
            f"🔑 Código ruta: {plan.get('codigo_ruta', 'N/A')}\n"
            f"📆 Fecha: {fecha_trabajo.strftime('%d/%m/%Y')} ({nombre_dia} - {weekday_code})\n\n"
            f"🏢 Sede: {plan.get('sede', 'N/A')}\n"
            f"👤 Supervisor: {plan.get('supervisor', 'N/A')}"
        )
    return (
        f"👤 Vendedor: {plan.get('vendedor_apoyo', 'N/A')}\n"
        f"🆔 ERP: {plan.get('codigo_erp_vendedor', 'N/A')}\n"
        f"🗺️ Ruta: {plan.get('ruta_oficial', 'N/A')}\n"
        f"🧭 Zona: {plan.get('zona', 'N/A')}\n"
        f"🔑 Código ruta: {plan.get('codigo_ruta', 'N/A')}\n"
        f"📆 Fecha: {fecha_trabajo.strftime('%d/%m/%Y')} ({nombre_dia} - {weekday_code})\n\n"
        f"🏢 Sede: {plan.get('sede', 'N/A')}\n"
        f"👤 Supervisor: {plan.get('supervisor', 'N/A')}"
    )


def build_confirmation_summary(fecha_trabajo: date, weekday_code: str, plan: Dict[str, Any]) -> str:
    """
    Builds the standardized confirmation summary shown to the supervisor
    before writing to PLANIFICACION_DIARIA, adapted to the modality
    (see build_plan_details).
    """
    return (
        "📋 *CONFIRMA TU PLANIFICACIÓN*\n\n"
        f"{build_plan_details(fecha_trabajo, weekday_code, plan)}\n\n"
        "¿Registrar?\n\n"
        "✅ CONFIRMAR\n"
        "❌ CORREGIR"
    )


def build_current_plan_message(
    fecha_trabajo: date,
    weekday_code: str,
    saved_plan: Dict[str, Any],
    can_cancel: bool = True
) -> str:
    """
    Answer to CORREGIR when a plan is already saved: shows THAT plan (not the
    pending draft) and asks for the replacement. `can_cancel` adds the
    "CANCELAR" hint, which only makes sense while a draft is pending
    (AWAITING_CONFIRMATION); with nothing pending (IDLE) there is nothing to cancel.
    """
    message = (
        "📋 Tu planificación actual es:\n\n"
        f"{build_plan_details(fecha_trabajo, weekday_code, saved_plan)}\n\n"
        "✍️ Envía la nueva planificación para reemplazarla."
    )
    if can_cancel:
        message += "\nO *CANCELAR* para dejarla como está."
    return message


def build_confirmation_summary_update(fecha_trabajo: date, weekday_code: str, plan: Dict[str, Any]) -> str:
    """Same as build_confirmation_summary, prefixed with a replace-warning."""
    notice = "⚠️ Vas a reemplazar tu planificación anterior."
    base = build_confirmation_summary(fecha_trabajo, weekday_code, plan)
    return f"{notice}\n\n{base}"


def build_selection_prompt(candidates: List[Dict[str, Any]]) -> str:
    """Builds the AWAITING_SELECTION prompt listing a seller's routes for today."""
    lines = ["⚠️ *Encontré varias rutas para hoy:*\n"]
    for idx, route in enumerate(candidates, start=1):
        lines.append(f"{idx}. {route.get('RUTA', 'N/A')} (Zona {route.get('ZONA', 'N/A')})")
    lines.append("\nResponde con el número de la ruta, o *CANCELAR*.")
    return "\n".join(lines)


ROUTE_LIST_PAGE_SIZE = 25


def route_list_pages(total: int, page_size: int = ROUTE_LIST_PAGE_SIZE) -> int:
    """Number of pages needed to show `total` routes."""
    return max(1, -(-total // page_size))


def build_route_list(
    fecha_trabajo: date,
    routes: List[Dict[str, Any]],
    page: int = 1,
    page_size: int = ROUTE_LIST_PAGE_SIZE
) -> str:
    """
    Builds the RUTA list: one line per route, `<Nº>. <RUTA> · <VENDEDOR> · <CODIGO RUTA>`.
    Numbers are global (page 2 continues after page 1) so the supervisor always
    answers with the number shown. The seller is printed as the master has it
    (e.g. 'VENDEDOR 10'); '(sin vendedor)' only replaces an empty cell.
    Zone and ERP code are intentionally not shown. Paginated only if there are
    more than `page_size` routes.
    """
    nombre_dia = _WEEKDAY_NAMES_ES[fecha_trabajo.weekday()].upper()
    pages = route_list_pages(len(routes), page_size)
    start = (page - 1) * page_size
    lines = [f"📋 *RUTAS DISPONIBLES — {nombre_dia} {fecha_trabajo.strftime('%d/%m/%Y')}*\n"]
    for idx, route in enumerate(routes[start:start + page_size], start=start + 1):
        # The seller is shown exactly as the master has it; only an empty cell falls back.
        seller = str(route.get("VENDEDOR") or "").strip() or "(sin vendedor)"
        lines.append(f"{idx}. {route.get('RUTA', 'N/A')} · {seller} · {route.get('CODIGO RUTA', 'N/A')}")
    lines.append("\nEnvía el *NÚMERO* de la ruta que vas a cubrir (ej. 3).")
    if pages > 1:
        lines.append(f"Página {page} de {pages}. Envía *LISTA {page % pages + 1}* para ver más.")
    lines.append("O envía *CANCELAR* para salir.")
    return "\n".join(lines)


def build_rejection_message(reason: str, current_active_planning: Optional[Dict[str, Any]] = None) -> str:
    """
    Builds a structured rejection response.
    Explicitly informs the supervisor that their previous planning remains unaltered if one exists.
    """
    lines = [
        "❌ *SOLICITUD RECHAZADA*",
        f"\nMotivo: {reason}\n"
    ]
    if current_active_planning:
        prev_route = current_active_planning.get("Ruta_Oficial", "N/A")
        prev_seller = current_active_planning.get("Vendedor_Apoyo", "N/A")
        lines.append("🛡️ *Tu planificación anterior se mantiene SIN CAMBIOS:*")
        lines.append(f"   - Ruta: {prev_route}")
        lines.append(f"   - Vendedor: {prev_seller}")
    else:
        lines.append("Por favor, envía nuevamente tu planificación con los datos corregidos.")

    return "\n".join(lines)
