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

MSG_AWAITING_CONFIRMATION_HELP = (
    "📋 Tienes una planificación pendiente de confirmación.\n\n"
    "👉 Responde *CONFIRMAR* para registrarla.\n"
    "👉 Responde *CORREGIR* para modificarla.\n"
    "👉 Responde *CANCELAR* para descartarla."
)

MSG_CORRECT_REQUESTED = "✍️ Envía la planificación corregida:"

MSG_CANCELLED_NO_CHANGES = (
    "🗑️ Solicitud cancelada. No se realizó ningún cambio."
)

MSG_SELECTION_INVALID = (
    "⚠️ No reconocí esa opción. Responde con el número de la ruta, o *CANCELAR*."
)

MSG_SELECTION_TOO_MANY_ERRORS = (
    "❌ Demasiados intentos inválidos. Envía nuevamente tu código de vendedor."
)

MSG_VENTA_ASK_CODE = (
    "🛒 ¿Cuál es el código del vendedor cuya ruta vas a cubrir?\n\n"
    "Escribe solo el código (ej. 1691) o *CANCELAR* para salir."
)

MSG_VENTA_CODE_INVALID = (
    "⚠️ No reconocí ese código. Envía solo el código del vendedor (3 a 6 dígitos), o *CANCELAR*."
)

MSG_HELP = (
    "📋 Para registrar tu planificación:\n\n"
    "Acompañar a un vendedor: escribe su código\n"
    "1691\n\n"
    "Otros casos:\n"
    "• venta (cubrir la ruta de un vendedor tú solo)\n"
    "• venta directa\n"
    "• oficina\n"
    "• AYUDA (este mensaje)\n\n"
    "Horario: lunes a viernes de 15:00 a 18:00."
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

MSG_REMINDER_SATURDAY_NOTICE = (
    "📅 Recordatorio: puedes registrar tu planificación del lunes durante la reunión "
    "de oficina del lunes por la mañana. ¡Buen fin de semana!"
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
