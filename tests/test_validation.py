"""
Unit tests for business validation rules: Route vs Day, Modalities and Catalog checks.
"""
from app.business.validation import (
    Modality,
    validate_planning_proposal
)

SAMPLE_MASTER = [
    {
        "RUTA": "ROUTE-001",
        "ZONA": "SUR",
        "DIA": "5-VI",
        "VENDEDOR": "SELLER_ALPHA",
        "CODIGO ERP": "1691",
        "CODIGO RUTA": "1100"
    },
    {
        "RUTA": "ROUTE-003",
        "ZONA": "ESTE",
        "DIA": "2-MA",
        "VENDEDOR": "SELLER_ALPHA",
        "CODIGO ERP": "1691",
        "CODIGO RUTA": "1042"
    }
]


def test_valid_accompaniment():
    """Acompañamiento con vendedor válido y ruta cuyo día coincide con el día de trabajo."""
    seller = SAMPLE_MASTER[0]
    route = SAMPLE_MASTER[0]
    res = validate_planning_proposal(
        modalidad=Modality.ACOMPANAMIENTO,
        target_weekday_code="5-VI",
        master_rows=SAMPLE_MASTER,
        matched_seller=seller,
        matched_route=route,
        observacion="Revisión clientes top"
    )
    assert res.is_valid is True
    assert res.validated_data["modalidad"] == "ACOMPAÑAMIENTO"
    assert res.validated_data["vendedor_apoyo"] == "SELLER_ALPHA"
    assert res.validated_data["codigo_erp_vendedor"] == "1691"
    assert res.validated_data["ruta_oficial"] == "ROUTE-001"
    assert res.validated_data["dia"] == "5-VI"


def test_route_day_mismatch():
    """Ruta válida pero cuyo día en el maestro (2-MA) no coincide con el día de trabajo (5-VI)."""
    seller = SAMPLE_MASTER[1]
    route = SAMPLE_MASTER[1]  # DIA = 2-MA
    res = validate_planning_proposal(
        modalidad=Modality.ACOMPANAMIENTO,
        target_weekday_code="5-VI",  # Día de trabajo es Viernes
        master_rows=SAMPLE_MASTER,
        matched_seller=seller,
        matched_route=route
    )
    assert res.is_valid is False
    assert res.error_code == "ROUTE_DAY_MISMATCH"
    assert "corresponde a los días 2-MA" in res.message


def test_office_modality():
    """Oficina no requiere vendedor ni ruta y no valida el día."""
    res = validate_planning_proposal(
        modalidad=Modality.OFICINA,
        target_weekday_code="5-VI",
        master_rows=SAMPLE_MASTER,
        observacion="Informes mensuales"
    )
    assert res.is_valid is True
    assert res.validated_data["modalidad"] == "OFICINA"
    assert res.validated_data["vendedor_apoyo"] == "N/A"
    assert res.validated_data["ruta_oficial"] == "OFICINA"
    assert res.validated_data["dia"] == "N/A"
    assert res.validated_data["observaciones"] == "Informes mensuales"


def test_direct_sale_modality():
    """Venta directa requiere ruta válida coincidente con el día pero no vendedor."""
    route = SAMPLE_MASTER[0]  # DIA = 5-VI
    res = validate_planning_proposal(
        modalidad=Modality.VENTA_DIRECTA,
        target_weekday_code="5-VI",
        master_rows=SAMPLE_MASTER,
        matched_route=route
    )
    assert res.is_valid is True
    assert res.validated_data["modalidad"] == "VENTA DIRECTA"
    assert res.validated_data["vendedor_apoyo"] == "VENTA DIRECTA"
    assert res.validated_data["codigo_erp_vendedor"] == "N/A"
    assert res.validated_data["ruta_oficial"] == "ROUTE-001"


def test_missing_seller_in_accompaniment():
    """Acompañamiento sin vendedor especificado debe fallar con MISSING_SELLER."""
    route = SAMPLE_MASTER[0]
    res = validate_planning_proposal(
        modalidad=Modality.ACOMPANAMIENTO,
        target_weekday_code="5-VI",
        master_rows=SAMPLE_MASTER,
        matched_seller=None,
        matched_route=route
    )
    assert res.is_valid is False
    assert res.error_code == "MISSING_SELLER"
