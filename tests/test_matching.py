"""
Unit tests for text normalization, deterministic matching and RapidFuzz fuzzy matching.
"""
from app.business.matching import (
    normalize_text,
    extract_route_number,
    match_item,
    MatchStatus
)

SAMPLE_CATALOG = [
    {"RUTA": "ROUTE-001", "VENDEDOR": "SELLER_ALPHA", "DIA": "5-VI"},
    {"RUTA": "ROUTE-002", "VENDEDOR": "SELLER_GAMMA", "DIA": "5-VI"},
    {"RUTA": "ROUTE-003", "VENDEDOR": "SELLER_DELTA", "DIA": "2-MA"},
    {"RUTA": "ROUTE-004", "VENDEDOR": "SELLER_EPSILON", "DIA": "3-MI"},
    {"RUTA": "ALT-ROUTE-004", "VENDEDOR": "SELLER_ZETA", "DIA": "3-MI"}
]


def test_normalize_text():
    """Verifica la limpieza exhaustiva de tildes, mayúsculas, guiones y espacios."""
    assert normalize_text("  séller alpha  ") == "SELLER ALPHA"
    assert normalize_text("DTS--77__SUR") == "DTS 77 SUR"
    assert normalize_text("María  José   Gómez") == "MARIA JOSE GOMEZ"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


def test_extract_route_number():
    """Verifica la extracción de dígitos de ruta en lenguaje natural."""
    assert extract_route_number("voy a la ruta 77") == "77"
    assert extract_route_number("DTS-81") == "81"
    assert extract_route_number("en la 12") == "12"
    assert extract_route_number("oficina") is None


def test_exact_and_normalized_seller_match():
    """Verifica coincidencia exacta y normalizada (con tildes invertidas o mayúsculas/minúsculas)."""
    res1 = match_item("SELLER_ALPHA", SAMPLE_CATALOG, key="VENDEDOR")
    assert res1.status == MatchStatus.OK
    assert res1.match["VENDEDOR"] == "SELLER_ALPHA"

    res2 = match_item("séller alpha", SAMPLE_CATALOG, key="VENDEDOR")
    assert res2.status == MatchStatus.OK
    assert res2.match["VENDEDOR"] == "SELLER_ALPHA"


def test_fuzzy_seller_match():
    """Verifica coincidencia fuzzy para errores de escritura (ej. 'Seler Alpha' con una letra menos)."""
    res = match_item("Seler Alpha", SAMPLE_CATALOG, key="VENDEDOR")
    assert res.status == MatchStatus.OK
    assert res.match["VENDEDOR"] == "SELLER_ALPHA"


def test_route_number_unique_match():
    """Verifica que el número '001' encuentre unívocamente la ruta 'ROUTE-001'."""
    res = match_item("ruta 001", SAMPLE_CATALOG, key="RUTA")
    assert res.status == MatchStatus.OK
    assert res.match["RUTA"] == "ROUTE-001"


def test_ambiguous_match():
    """Verifica que 'ruta 004' devuelva AMBIGUO al coincidir con ROUTE-004 y ALT-ROUTE-004."""
    res = match_item("ruta 004", SAMPLE_CATALOG, key="RUTA")
    assert res.status == MatchStatus.AMBIGUO
    assert len(res.candidates) >= 2


def test_not_found_match():
    """Verifica que un término inexistente devuelva NO_ENCONTRADO."""
    res = match_item("Vendedor Inexistente 999", SAMPLE_CATALOG, key="VENDEDOR")
    assert res.status == MatchStatus.NO_ENCONTRADO
