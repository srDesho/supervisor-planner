"""
Standardized WhatsApp message templates for Supervisor Planner.
"""
from typing import Dict, List


MSG_UNRECOGNIZED_SENDER = (
    "🔒 *ACCESO NO AUTORIZADO*\n\n"
    "Hola, tu número no se encuentra registrado en la lista de supervisores autorizados de Company.\n"
    "Si consideras que esto es un error, por favor comunícate con el Administrador del sistema."
)

MSG_SELLER_CODE_NOT_FOUND = (
    "⚠️ No encontré ningún vendedor con ese código en tu sede. Verifica el código e intenta de nuevo."
)

MSG_SUPERVISOR_NO_ZONE = (
    "⚠️ Tu registro está incompleto. Contacta al administrador del sistema para que asigne tu zona."
)

MSG_SELLER_WRONG_ZONE = (
    "⚠️ El código {codigo} pertenece a {vendedor} ({zona_vendedor}). Esa zona no está a tu cargo. Verifica con tu supervisor."
)

MSG_SELLER_ALREADY_ASSIGNED = (
    "⚠️ El vendedor {vendedor} ya fue registrado para el {fecha} por {otro_supervisor}. No puedes registrar al mismo vendedor el mismo día."
)

MSG_SELLER_NO_ROUTE_TODAY = (
    "⚠️ Ese vendedor no tiene una ruta asignada para el día de trabajo de hoy."
)

MSG_UNCLEAR = (
    "🤔 No entendí tu mensaje. Escribe *AYUDA* para ver el formato."
)

MSG_REGISTERED_OK = (
    "✅ *PLANIFICACIÓN REGISTRADA EXITOSAMENTE*\n\n"
    "Tu jornada ha sido consolidada en el sistema."
)

MSG_UPDATED_OK = (
    "✅ *PLANIFICACIÓN ACTUALIZADA EXITOSAMENTE*\n\n"
    "Los cambios han sido aplicados correctamente sobre tu planificación activa."
)

# --- Numbered menus -------------------------------------------------------
# Every menu is additive: the text commands (RUTA, OFICINA, CONFIRMAR, ...) keep
# working. A number only means something while the menu that offered it is the
# last thing the bot sent (conversation state AWAITING_*).

_MAIN_MENU_ITEMS = (
    "1️⃣ Acompañar a un vendedor\n"
    "2️⃣ Cubrir una ruta tú solo\n"
    "3️⃣ Venta directa\n"
    "4️⃣ Oficina"
)
_ANSWER_LINE = "Responde con el número."
_MAIN_MENU_OPTIONS = _MAIN_MENU_ITEMS + "\n\n" + _ANSWER_LINE

# Menu 1: AYUDA, unknown message (no saved plan), CORREGIR. {dia} {fecha}: target work day.
MSG_MAIN_MENU = "📋 ¿Qué quieres registrar para el {dia} {fecha}?\n\n" + _MAIN_MENU_OPTIONS

# Menu 1 for a supervisor who ALREADY has a saved plan: same options plus a way out.
MSG_MAIN_MENU_KEEP = (
    "📋 ¿Qué quieres registrar para el {dia} {fecha}?\n\n"
    + _MAIN_MENU_ITEMS
    + "\n5️⃣ Dejar mi planificación como está\n\n"
    + _ANSWER_LINE
)

MSG_KEEP_PLAN_OK = "✅ Listo, tu planificación se mantiene sin cambios."

# CANCELAR (or "no", "salir"...) from someone with a saved plan and nothing pending.
MSG_NOTHING_PENDING = "✅ No hay cambios pendientes. Tu planificación sigue activa."

MSG_MAIN_MENU_COMMANDS_HINT = (
    "También puedes escribir: ruta, venta directa, oficina o el código de un vendedor."
)

# Menu 5: appended to the automatic "no planning yet" reminder.
MSG_REMINDER_MENU = "📋 ¿Qué quieres registrar?\n\n" + _MAIN_MENU_OPTIONS

# First line of the answer to CORREGIR when nothing is saved; the main menu follows.
MSG_NO_PLAN_INFO = "📋 No tienes una planificación registrada para el {fecha}."

# Menu 2: RUTA.
MSG_RUTA_MENU = (
    "🚗 ¿Cómo quieres elegir la ruta?\n\n"
    "1️⃣ Por código de vendedor\n"
    "2️⃣ Por código de ruta\n"
    "3️⃣ Ver las rutas de todos los vendedores de ese día\n\n"
    "Responde con el número.\n"
    "O *CANCELAR* para salir."
)

MSG_ASK_SELLER_CODE = (
    "🔢 Envía el código del vendedor (ej. 4287).\n"
    "O *CANCELAR* para salir."
)

MSG_ASK_ROUTE_CODE = (
    "🔢 Envía el código de la ruta (ej. 105), o *LISTA* para ver las rutas del día.\n"
    "O *CANCELAR* para salir."
)

MSG_SELLER_CODE_INVALID = "⚠️ Envía solo el código del vendedor (un número), o *CANCELAR*."

MSG_ROUTE_CODE_INVALID = "⚠️ Envía solo el código de la ruta (un número), *LISTA* o *CANCELAR*."

MSG_LIST_PICK_INVALID = "⚠️ Responde con el número de la ruta de la lista, o *CANCELAR*."

MSG_ROUTE_CODE_NOT_FOUND = (
    "⚠️ No encontré ninguna ruta con ese código para el día de trabajo. "
    "Verifica el código o envía *LISTA*."
)

MSG_PLAN_ALREADY_ACTIVE = "✅ Esa planificación ya está activa. No hay cambios."

MSG_CANCELLED_NO_CHANGES = (
    "🗑️ Solicitud cancelada. No se realizó ningún cambio."
)

MSG_SELECTION_INVALID = (
    "⚠️ No reconocí esa opción. Responde con el número de la ruta, o *CANCELAR*."
)

MSG_SELECTION_TOO_MANY_ERRORS = (
    "❌ Demasiados intentos inválidos. Envía nuevamente tu código de vendedor."
)

MSG_RUTA_CODE_NOT_FOUND = (
    "⚠️ No encontré ningún vendedor ni ruta con ese código para el día de trabajo. "
    "Verifica el código o envía LISTA."
)

MSG_RUTA_LIST_OUT_OF_RANGE = (
    "⚠️ Número inválido, la lista tiene {total} rutas."
)

MSG_RUTA_LIST_EMPTY = (
    "⚠️ No hay rutas disponibles para el {dia} en tu zona."
)

MSG_RUTA_LIST_BAD_PAGE = (
    "⚠️ Esa página no existe, la lista tiene {pages} página(s)."
)

MSG_REMINDER_PENDING_SUBMISSION = (
    "⏰ Aún no hemos recibido tu planificación para el {fecha} ({dia})."
)

MSG_REMINDER_AWAITING_CONFIRMATION = (
    "📋 Tu planificación está pendiente de confirmación. Responde CONFIRMAR."
)

MSG_REMINDER_AWAITING_SELECTION = (
    "⚠️ Tienes una selección pendiente. Responde con el número de la ruta."
)

MSG_REMINDER_AWAITING_SELLER_CODE = (
    "🔢 Estabas por enviar el código de un vendedor para acompañarlo. "
    "Envíalo, o *CANCELAR* para salir."
)

MSG_REMINDER_AWAITING_RUTA_CODE = (
    "🚗 Estabas eligiendo la ruta que vas a cubrir. Envía el código del vendedor, "
    "el código de la ruta o *LISTA*; o *CANCELAR* para salir."
)

MSG_PROCESSING_ERROR = (
    "⚠️ Tuve un problema procesando tu mensaje. Intenta de nuevo en unos segundos."
)


def build_escalation_alert(
    fecha_trabajo: str,
    uncompleted_supervisors: List[Dict[str, str]]
) -> str:
    """Builds the escalation alert sent to ADMIN_PHONE when the planning window closes."""
    lines = ["⚠️ PLANIFICACIÓN PENDIENTE\n"]
    for sup in uncompleted_supervisors:
        lines.append(f"• {sup['supervisor']} ({sup['sede']})")
    lines.append(f"\nFecha de trabajo: {fecha_trabajo}")
    return "\n".join(lines)
