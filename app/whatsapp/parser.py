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


# ---------------------------------------------------------------------------
# Command matching = EXACT equality on the normalized text.
#
# A command only matches when the whole message IS the command ("corregir",
# "Corregir.", " CORREGIR "); never when a sentence merely contains it
# ("quiero corregir algo", "necesito una ayuda", "el ok de la reunión").
# Nothing here may use substring / `in` / `search` to decide a command.
# ---------------------------------------------------------------------------

# Trailing punctuation that never changes the meaning of a command.
_TRAILING_PUNCTUATION = ".,;!?"


def normalize_command(text: str) -> str:
    """
    The single normalization every command comparison goes through:
    lower case, no accents, trimmed, inner whitespace collapsed to one space and
    the trailing run of '. , ; ! ?' removed ("Corregir." == "corregir").
    Inner punctuation is left alone.
    """
    collapsed = " ".join(unidecode(text or "").lower().split())
    return collapsed.rstrip(_TRAILING_PUNCTUATION + " ")


_CODE_ONLY_PATTERN = re.compile(r"\d{3,6}")
_LISTA_PATTERN = re.compile(r"lista(?: (\d+))?")
# Digits, optionally followed by a ')' ("1)"): for numbers and menu options only.
_NUMBER_PATTERN = re.compile(r"(\d+)\s*\)?")
_MENU_CHOICE_PATTERN = re.compile(r"([1-9])\s*\)?")
# A known typo of "confirmar" (extra 'r'). Still a whole-message match.
_CONFIRM_TYPO_PATTERN = re.compile(r"confir+mar")

# Whole-message words, accent-free and lower case (so "sí" is "si").
_VENTA_DIRECTA_WORDS = {"venta directa"}
_RUTA_WORDS = {"ruta"}
_OFICINA_WORDS = {"oficina"}
_HELP_WORDS = {"ayuda", "help"}
_CONFIRM_WORDS = {"confirmar", "confirma", "confirmo", "ok", "okey", "dale", "listo", "si"}
_CORRECT_WORDS = {"corregir", "corrige", "corrijo", "cambiar", "cambia", "editar", "edito"}
_CANCEL_WORDS = {"cancelar", "cancela", "cancelo", "descartar", "no", "nop", "salir", "salgo"}


def extract_planning_intent(text: str) -> Dict[str, Optional[str]]:
    """
    Deterministic (non-AI) intent extraction for the planning flow.
    Returns {"type": ..., "codigo_erp": str | None, "raw": text}.

    Every command matches only when the whole (normalized) message is that
    command, so the order of the checks does not matter: no text can be two
    commands at once.
    """
    raw = text or ""
    normalized = normalize_command(raw)

    if normalized in _VENTA_DIRECTA_WORDS:
        return {"type": "venta_directa", "codigo_erp": None, "raw": raw}
    if normalized in _RUTA_WORDS:
        return {"type": "ruta", "codigo_erp": None, "raw": raw}
    if normalized in _OFICINA_WORDS:
        return {"type": "oficina", "codigo_erp": None, "raw": raw}
    if _CODE_ONLY_PATTERN.fullmatch(normalized):
        return {"type": "code_only", "codigo_erp": normalized, "raw": raw}
    if normalized in _HELP_WORDS:
        return {"type": "help", "codigo_erp": None, "raw": raw}
    if normalized in _CONFIRM_WORDS or _CONFIRM_TYPO_PATTERN.fullmatch(normalized):
        return {"type": "confirm", "codigo_erp": None, "raw": raw}
    if normalized in _CORRECT_WORDS:
        return {"type": "correct", "codigo_erp": None, "raw": raw}
    if normalized in _CANCEL_WORDS:
        return {"type": "cancel", "codigo_erp": None, "raw": raw}
    return {"type": "unknown", "codigo_erp": None, "raw": raw}


def parse_number(text: str) -> Optional[str]:
    """
    The digits of a message that is just a number ("10", " 10. ", "10)"), else None.
    Used wherever a bare number is expected (codes, list positions, selections).
    """
    match = _NUMBER_PATTERN.fullmatch(normalize_command(text))
    return match.group(1) if match else None


def extract_ruta_input(text: str) -> Dict[str, Any]:
    """
    Classifies what a supervisor sends while the bot waits for the RUTA code
    (AWAITING_RUTA_CODE). Returns one of:
    {"type": "cancel"}, {"type": "lista", "page": int},
    {"type": "number", "value": "<digits>"}, {"type": "invalid"}.
    """
    if extract_planning_intent(text)["type"] == "cancel":
        return {"type": "cancel"}
    normalized = normalize_command(text)
    lista = _LISTA_PATTERN.fullmatch(normalized)
    if lista:
        return {"type": "lista", "page": int(lista.group(1)) if lista.group(1) else 1}
    number = parse_number(text)
    if number is not None and len(number) <= 6:
        return {"type": "number", "value": number}
    return {"type": "invalid"}


def parse_menu_choice(text: str) -> Optional[int]:
    """
    The option picked in a numbered menu, or None. ONLY an exact single digit
    counts ("1", " 1 ", "1.", "1)"): "10" is a code and "1 de octubre" is a
    sentence, neither is option 1.
    """
    match = _MENU_CHOICE_PATTERN.fullmatch(normalize_command(text))
    return int(match.group(1)) if match else None
