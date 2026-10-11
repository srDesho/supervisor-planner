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


def build_confirmation_summary(fecha_trabajo: date, weekday_code: str, plan: Dict[str, Any]) -> str:
    """
    Builds the standardized confirmation summary shown to the supervisor
    before writing to PLANIFICACION_DIARIA, adapted to the modality:
    - OFICINA / VENTA DIRECTA: minimal (no seller, route or zone to show).
    - VENTA: modality line + name of the seller whose route is covered.
    - ACOMPAÑAMIENTO: the full summary.
    """
    nombre_dia = _WEEKDAY_NAMES_ES[fecha_trabajo.weekday()]
    modalidad = plan.get("modalidad")
    if modalidad in ("OFICINA", "VENTA DIRECTA"):
        return (
            "📋 *CONFIRMA TU PLANIFICACIÓN*\n\n"
            f"🏢 Modalidad: {modalidad}\n"
            f"📆 Fecha: {fecha_trabajo.strftime('%d/%m/%Y')} ({nombre_dia} - {weekday_code})\n"
            f"🏢 Sede: {plan.get('sede', 'N/A')}\n"
            f"👤 Supervisor: {plan.get('supervisor', 'N/A')}\n\n"
            "¿Registrar?\n\n"
            "✅ CONFIRMAR\n"
            "❌ CORREGIR"
        )
    if modalidad == "VENTA":
        # Vendedor_Apoyo is empty for VENTA (see _build_seller_plan), so no
        # "Vendedor:" label; show only the name of the seller whose route is covered.
        vendedor_line = (
            "🛒 Modalidad: VENTA (cubres la ruta solo)\n"
            f"👤 {plan.get('vendedor_nombre', 'N/A')}\n"
        )
    else:
        vendedor_line = f"👤 Vendedor: {plan.get('vendedor_apoyo', 'N/A')}\n"
    return (
        "📋 *CONFIRMA TU PLANIFICACIÓN*\n\n"
        f"{vendedor_line}"
        f"🆔 ERP: {plan.get('codigo_erp_vendedor', 'N/A')}\n"
        f"🗺️ Ruta: {plan.get('ruta_oficial', 'N/A')}\n"
        f"🧭 Zona: {plan.get('zona', 'N/A')}\n"
        f"🔑 Código ruta: {plan.get('codigo_ruta', 'N/A')}\n"
        f"📆 Fecha: {fecha_trabajo.strftime('%d/%m/%Y')} ({nombre_dia} - {weekday_code})\n\n"
        f"🏢 Sede: {plan.get('sede', 'N/A')}\n"
        f"👤 Supervisor: {plan.get('supervisor', 'N/A')}\n\n"
        "¿Registrar?\n\n"
        "✅ CONFIRMAR\n"
        "❌ CORREGIR"
    )


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
