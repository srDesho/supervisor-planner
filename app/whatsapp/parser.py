"""
Parser and data extractor for WAHA webhook events.
Cleans WhatsApp IDs, normalizes phone numbers and extracts message body.
Also holds the deterministic (non-AI) command/intent recognizers used by
the planning flow: extract_planning_intent().
"""
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from unidecode import unidecode


class ParsedWhatsAppMessage(BaseModel):
    event: str
    session: str
    message_id: str
    from_phone: str
    from_full: Optional[str] = None
    sender_name: Optional[str] = None
    body: str
    from_me: bool = False
    timestamp: Optional[int] = None
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


def clean_phone_number(raw_phone: str) -> str:
    """
    Cleans raw WhatsApp identifier into a normalized phone string:
    '59170000001@c.us' -> '59170000001'
    '+591 70000001'   -> '59170000001'
    """
    if not raw_phone:
        return ""
    # Strip WA domain
    phone_part = raw_phone.split("@")[0]
    # Remove non-digits
    digits_only = "".join(ch for ch in phone_part if ch.isdigit())
    return digits_only


def parse_waha_webhook(payload: Dict[str, Any]) -> Optional[ParsedWhatsAppMessage]:
    """
    Parses a WAHA incoming webhook dictionary into a typed ParsedWhatsAppMessage.
    Returns None if payload is not a relevant message event.
    """
    event = payload.get("event", "")
    session = payload.get("session", "default")
    data = payload.get("payload", {})

    # Check if this is a message event
    if event not in ("message", "message.any"):
        return None

    from_me = bool(data.get("fromMe", False))
    if from_me:
        # Ignore messages sent by the bot itself
        return None

    raw_from = data.get("from", "")
    body = data.get("body", "") or ""
    message_id = data.get("id", "")
    timestamp = data.get("timestamp")
    sender_name = data.get("_data", {}).get("notifyName") or data.get("notifyName")

    cleaned_phone = clean_phone_number(raw_from)
    if not cleaned_phone:
        return None

    return ParsedWhatsAppMessage(
        event=event,
        session=session,
        message_id=str(message_id),
        from_phone=cleaned_phone,
        from_full=raw_from,
        sender_name=sender_name,
        body=body.strip(),
        from_me=from_me,
        timestamp=timestamp,
        raw_payload=payload
    )


_CODE_ONLY_PATTERN = re.compile(r"^(\d{3,6})$")
_VENTA_DIRECTA_PATTERN = re.compile(r"^venta\s+directa$")
_RUTA_PATTERN = re.compile(r"^ruta$")
_OFICINA_PATTERN = re.compile(r"\boficina\b")
# Text is accent-free and lowercase when matched, so "sí" arrives as "si".
#
# Long, unambiguous command words match as a whole word ANYWHERE in the
# message. "confir+mar" also tolerates the typo "confirrmar".
_CONFIRM_PATTERN = re.compile(r"\b(?:confir+mar|confirma|confirmo)\b")
_CORRECT_PATTERN = re.compile(
    r"\b(?:corregir|corrige|corrijo|cambiar|cambia|editar|edito)\b"
)
_CANCEL_PATTERN = re.compile(r"\b(?:cancelar|cancela|cancelo|descartar)\b")
# Short words collide with everyday sentences ("no tengo ruta", "ok gracias"),
# so they only count when they ARE the whole message (optionally followed by
# a single '.' or '!').
_CONFIRM_SHORT_PATTERN = re.compile(r"^(?:ok|okey|dale|listo|si)\s*[.!]?$")
_CANCEL_SHORT_PATTERN = re.compile(r"^(?:no|nop|salir|salgo)\s*[.!]?$")
_HELP_PATTERN = re.compile(r"\bayuda\b|\bhelp\b")


def _normalize_command(text: str) -> str:
    """Lowercase, accent-free, trimmed, with inner whitespace collapsed."""
    return " ".join(unidecode(text or "").lower().split())


def extract_planning_intent(text: str) -> Dict[str, Optional[str]]:
    """
    Deterministic (non-AI) intent extraction for the planning flow.
    Returns {"type": ..., "codigo_erp": str | None, "raw": text}.

    Evaluation order matters: "venta directa" (two words) is checked before
    "ruta" (one word).
    """
    raw = text or ""
    normalized = _normalize_command(raw)

    if _VENTA_DIRECTA_PATTERN.match(normalized):
        return {"type": "venta_directa", "codigo_erp": None, "raw": raw}
    if _RUTA_PATTERN.match(normalized):
        return {"type": "ruta", "codigo_erp": None, "raw": raw}
    if _OFICINA_PATTERN.search(normalized):
        return {"type": "oficina", "codigo_erp": None, "raw": raw}
    code_match = _CODE_ONLY_PATTERN.match(normalized)
    if code_match:
        return {"type": "code_only", "codigo_erp": code_match.group(1), "raw": raw}
    if _HELP_PATTERN.search(normalized):
        return {"type": "help", "codigo_erp": None, "raw": raw}
    if _CONFIRM_PATTERN.search(normalized) or _CONFIRM_SHORT_PATTERN.match(normalized):
        return {"type": "confirm", "codigo_erp": None, "raw": raw}
    if _CORRECT_PATTERN.search(normalized):
        return {"type": "correct", "codigo_erp": None, "raw": raw}
    if _CANCEL_PATTERN.search(normalized) or _CANCEL_SHORT_PATTERN.match(normalized):
        return {"type": "cancel", "codigo_erp": None, "raw": raw}
    return {"type": "unknown", "codigo_erp": None, "raw": raw}


_LISTA_PATTERN = re.compile(r"^lista(?:\s+(\d+))?$")
_NUMBER_PATTERN = re.compile(r"^\d{1,6}$")


def extract_ruta_input(text: str) -> Dict[str, Any]:
    """
    Classifies what a supervisor sends while the bot waits for the RUTA code
    (AWAITING_RUTA_CODE). Returns one of:
    {"type": "cancel"}, {"type": "lista", "page": int},
    {"type": "number", "value": "<digits>"}, {"type": "invalid"}.
    """
    if extract_planning_intent(text)["type"] == "cancel":
        return {"type": "cancel"}
    normalized = _normalize_command(text)
    lista = _LISTA_PATTERN.match(normalized)
    if lista:
        return {"type": "lista", "page": int(lista.group(1)) if lista.group(1) else 1}
    if _NUMBER_PATTERN.match(normalized):
        return {"type": "number", "value": normalized}
    return {"type": "invalid"}
