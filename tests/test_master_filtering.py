"""
Unit tests for MastersService sede->worksheet mapping and the no-zone-filter
rule for LPZ (Part 10.3): LPZ holds both La Paz and El Alto, distinguished
only by ZONA; the bot never filters by ZONA.
"""
from app.sheets.masters import MastersService, SEDE_TO_WORKSHEET


def test_sede_to_worksheet_mapping():
    assert SEDE_TO_WORKSHEET["SCZ"] == "PLANIFICACION_SCZ_RENOM"
    assert SEDE_TO_WORKSHEET["CBBA"] == "PLANIFICACION_CBBA_RENOM"
    assert SEDE_TO_WORKSHEET["LPZ"] == "PLANIFICACION_LPZ"


def test_lpz_reads_both_zones_without_filtering():
    svc = MastersService()
    svc.update_cache("LPZ", [
        {"RUTA": "R1", "ZONA": "LA PAZ", "DIA": "1-LU", "VENDEDOR": "X", "CODIGO ERP": "1", "CODIGO RUTA": "10"},
        {"RUTA": "R2", "ZONA": "EL ALTO", "DIA": "1-LU", "VENDEDOR": "Y", "CODIGO ERP": "2", "CODIGO RUTA": "20"},
    ])

    rows = svc.get_master_for_sede("LPZ")

    assert len(rows) == 2
    assert {r["ZONA"] for r in rows} == {"LA PAZ", "EL ALTO"}


def test_scz_and_cbba_caches_are_independent():
    svc = MastersService()
    svc.update_cache("SCZ", [{"RUTA": "SCZ-1", "ZONA": "N", "DIA": "1-LU", "VENDEDOR": "A", "CODIGO ERP": "100", "CODIGO RUTA": "1"}])
    svc.update_cache("CBBA", [{"RUTA": "CBBA-1", "ZONA": "S", "DIA": "1-LU", "VENDEDOR": "B", "CODIGO ERP": "200", "CODIGO RUTA": "2"}])

    assert svc.get_master_for_sede("SCZ")[0]["RUTA"] == "SCZ-1"
    assert svc.get_master_for_sede("CBBA")[0]["RUTA"] == "CBBA-1"


def test_get_seller_by_code_and_routes_for_day():
    svc = MastersService()
    svc.update_cache("SCZ", [
        {"RUTA": "R1", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR UNO", "CODIGO ERP": "4364", "CODIGO RUTA": "10"},
        {"RUTA": "R2", "ZONA": "S", "DIA": "5-VI", "VENDEDOR": "VENDEDOR UNO", "CODIGO ERP": "4364", "CODIGO RUTA": "20"},
    ])

    seller_rows = svc.get_seller_by_code("SCZ", "4364")
    assert len(seller_rows) == 2

    thursday_routes = svc.get_routes_for_seller_on_day("SCZ", "4364", "4-JU")
    assert len(thursday_routes) == 1
    assert thursday_routes[0]["RUTA"] == "R1"

    assert svc.get_seller_by_code("SCZ", "9999") == []
