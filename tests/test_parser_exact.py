"""
Command matching is EXACT equality on the normalized text: a command only
matches when the whole message IS the command, never when a sentence contains it.
Normalization: lower case, no accents, trimmed, inner spaces collapsed, trailing
run of '. , ; ! ?' removed ('Corregir.' == 'corregir'); numbers/menu options also
accept a final ')'.
"""
import pytest

from app.whatsapp.parser import (
    extract_planning_intent,
    extract_ruta_input,
    normalize_command,
    parse_menu_choice,
    parse_number,
)


# ---------- normalization ----------

@pytest.mark.parametrize("raw,expected", [
    ("  Corregir.  ", "corregir"),
    ("SÍ", "si"),
    ("venta    directa", "venta directa"),
    ("Venta Directa!!", "venta directa"),
    ("ok?.,;!", "ok"),
    ("Oficína", "oficina"),
    ("ok, gracias", "ok, gracias"),          # inner punctuation is left alone
    ("1)", "1)"),                            # ')' is only tolerated by numbers/menu options
    ("", ""),
    ("?!", ""),
])
def test_normalize_command(raw, expected):
    assert normalize_command(raw) == expected


# ---------- sentences that merely CONTAIN a command are not commands ----------

@pytest.mark.parametrize("text", [
    "quiero corregir algo",
    "necesito una ayuda",
    "el ok de la reunión",
    "dame la ruta por favor",
    "necesito ir a oficina mañana",
    "venta directa es mejor",
    "confirmo el plan",
    "quiero cancelar",
    "no cancelar",
    "quiero cambiar la ruta",
    "ok pero cambia la ruta",
    "ok gracias",
    "ok, gracias",
    "no tengo ruta para hoy",
    "no, mejor mañana",
    "salgo a ruta",
    "dale que si",
    "listo para salir",
    "ayuda por favor",
    "help me",
    "ruta 105",
    "oficina hoy",
    "lista de rutas",
    "4287 gracias",
    "1 de octubre",
    "hola",
    "",
])
def test_sentences_are_not_commands(text):
    assert extract_planning_intent(text)["type"] == "unknown"


# ---------- exact commands keep working, with tolerance ----------

@pytest.mark.parametrize("text,expected", [
    # CONFIRMAR
    ("CONFIRMAR", "confirm"), ("confirmar", "confirm"), ("Confirmar.", "confirm"), ("confirma", "confirm"),
    ("confirmo!", "confirm"), (" sí ", "confirm"), ("si", "confirm"), ("SI", "confirm"), ("ok", "confirm"),
    ("Ok.", "confirm"), ("okey", "confirm"), ("dale", "confirm"), ("listo", "confirm"),
    ("confirrmar", "confirm"), ("Confirrmar.", "confirm"),
    # CORREGIR
    ("CORREGIR", "correct"), ("corregir.", "correct"), (" CORREGIR ", "correct"), ("corrige", "correct"),
    ("corrijo", "correct"), ("cambiar", "correct"), ("cambia", "correct"), ("editar", "correct"),
    ("edito", "correct"), ("Corregir?", "correct"),
    # CANCELAR
    ("CANCELAR", "cancel"), ("cancelar.", "cancel"), ("cancela", "cancel"), ("cancelo", "cancel"),
    ("descartar", "cancel"), ("no", "cancel"), ("No.", "cancel"), ("nop", "cancel"), ("salir", "cancel"),
    ("salgo", "cancel"),
    # RUTA / OFICINA / VENTA DIRECTA
    ("RUTA", "ruta"), ("ruta", "ruta"), ("Ruta.", "ruta"), ("ruta.", "ruta"),
    ("OFICINA", "oficina"), ("oficina.", "oficina"), ("Oficína", "oficina"),
    ("VENTA DIRECTA", "venta_directa"), ("venta    directa", "venta_directa"), ("Venta directa.", "venta_directa"),
    # AYUDA
    ("AYUDA", "help"), ("ayuda.", "help"), ("Ayuda!", "help"), ("help", "help"), ("HELP", "help"),
    # direct seller code
    ("4287", "code_only"), ("4287.", "code_only"), (" 4287 ", "code_only"), ("123", "code_only"),
    ("123456", "code_only"),
])
def test_exact_commands_with_tolerance(text, expected):
    assert extract_planning_intent(text)["type"] == expected


def test_direct_code_extracts_the_digits_only():
    assert extract_planning_intent("4287.")["codigo_erp"] == "4287"
    assert extract_planning_intent(" 4287 ")["codigo_erp"] == "4287"


@pytest.mark.parametrize("text", ["12", "1234567", "4287a", "4 287", "42.87"])
def test_numbers_that_are_not_a_3_to_6_digit_code_are_not_a_direct_code(text):
    assert extract_planning_intent(text)["type"] == "unknown"


# ---------- menu options: only an exact single digit ----------

@pytest.mark.parametrize("text,expected", [
    ("1", 1), (" 1 ", 1), ("1.", 1), ("1)", 1), ("1 )", 1), ("  3  ", 3), ("4!", 4), ("5", 5),
    ("10", None), ("12", None), ("1 de octubre", None), ("1a", None), ("uno", None), ("0", None),
    ("4287", None), ("", None), ("1,5", None), ("11", None),
])
def test_parse_menu_choice(text, expected):
    assert parse_menu_choice(text) == expected


# ---------- bare numbers ----------

@pytest.mark.parametrize("text,expected", [
    ("10", "10"), (" 10. ", "10"), ("10)", "10"), ("1", "1"), ("0", "0"),
    ("10 y 20", None), ("diez", None), ("", None), ("1,5", None),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_parse_number_never_raises_on_unicode_digits():
    # str.isdigit() accepts '²' and then int('²') raises; a regex match does not.
    assert parse_number("²") in ("2", None)
    int(parse_number("²") or "0")


# ---------- the RUTA flow classifier ----------

@pytest.mark.parametrize("text,expected", [
    ("LISTA", {"type": "lista", "page": 1}),
    ("lista.", {"type": "lista", "page": 1}),
    ("lista 3", {"type": "lista", "page": 3}),
    ("Lista  2.", {"type": "lista", "page": 2}),
    ("10", {"type": "number", "value": "10"}),
    ("10.", {"type": "number", "value": "10"}),
    ("1)", {"type": "number", "value": "1"}),
    ("105", {"type": "number", "value": "105"}),
    ("CANCELAR", {"type": "cancel"}),
    ("cancelar.", {"type": "cancel"}),
    ("no", {"type": "cancel"}),
    ("quiero cancelar algo", {"type": "invalid"}),
    ("lista de rutas", {"type": "invalid"}),
    ("lista 3 por favor", {"type": "invalid"}),
    ("1234567", {"type": "invalid"}),
    ("banana", {"type": "invalid"}),
])
def test_extract_ruta_input(text, expected):
    assert extract_ruta_input(text) == expected
