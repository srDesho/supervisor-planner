"""
Phone number normalization utilities.

Regla de oro: TODO teléfono que entre al sistema (WhatsApp, REGISTRAR, hoja)
pasa por normalize_phone() antes de compararse o guardarse.
"""


def normalize_phone(raw) -> str:
    """
    Normaliza un número de teléfono a los 8 dígitos locales bolivianos,
    sin código de país, espacios, guiones, '+' ni sufijos de WhatsApp
    (@c.us, @lid, etc.).

    Acepta str, int, float o None — gspread devuelve celdas numéricas como
    int/float, no como str, así que este cast defensivo es obligatorio.

    >>> normalize_phone("59169105312")
    '69105312'
    >>> normalize_phone("59169105312@c.us")
    '69105312'
    >>> normalize_phone("+591 691-05312")
    '69105312'
    >>> normalize_phone("69105312")
    '69105312'
    >>> normalize_phone(69105312)
    '69105312'
    >>> normalize_phone("691 05 312")
    '69105312'
    >>> normalize_phone("123")
    ''
    >>> normalize_phone(None)
    ''
    """
    if raw is None or raw == "":
        return ""

    # Defensive: gspread may return numeric cells as int/float.
    raw = str(raw)

    digits = "".join(ch for ch in raw if ch.isdigit())

    if digits.startswith("591") and len(digits) > 8:
        digits = digits[3:]

    if len(digits) < 8:
        return ""

    return digits[-8:]