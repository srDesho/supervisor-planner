"""
Business rules validation engine.
Enforces strict Company operational rules:
- Route vs Day consistency
- Modality-specific requirements (ACOMPAÑAMIENTO, VENTA DIRECTA, OFICINA)
- Seller and Route existence in Sede master catalog
"""
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class Modality(str, Enum):
    ACOMPANAMIENTO = "ACOMPAÑAMIENTO"
    VENTA_DIRECTA = "VENTA DIRECTA"
    OFICINA = "OFICINA"


class ValidationResult(BaseModel):
    is_valid: bool
    error_code: Optional[str] = None
    message: str = ""
    validated_data: Optional[Dict[str, Any]] = None


def normalize_modality(text: Optional[str]) -> Optional[Modality]:
    """Normalizes natural language modality to official Modality enum."""
    if not text:
        return None
    cleaned = text.strip().upper()
    if "ACOMPA" in cleaned:
        return Modality.ACOMPANAMIENTO
    elif "DIRECT" in cleaned or "VENTA" in cleaned:
        return Modality.VENTA_DIRECTA
    elif "OFICINA" in cleaned or "ADMIN" in cleaned:
        return Modality.OFICINA
    return None


def validate_planning_proposal(
    modalidad: Modality,
    target_weekday_code: str,
    master_rows: List[Dict[str, Any]],
    matched_seller: Optional[Dict[str, Any]] = None,
    matched_route: Optional[Dict[str, Any]] = None,
    observacion: str = ""
) -> ValidationResult:
    """
    Validates a complete planning proposal against business rules:
    - OFICINA: does not require seller or route, bypasses day validation.
    - VENTA DIRECTA: requires route matching target day. Seller is 'VENTA DIRECTA'.
    - ACOMPAÑAMIENTO: requires both seller and route matching target day.
    """
    if modalidad == Modality.OFICINA:
        return ValidationResult(
            is_valid=True,
            message="Modalidad Oficina válida",
            validated_data={
                "modalidad": Modality.OFICINA.value,
                "vendedor_apoyo": "N/A",
                "codigo_erp_vendedor": "N/A",
                "ruta_oficial": "OFICINA",
                "zona": "N/A",
                "codigo_ruta": "N/A",
                "dia": "N/A",
                "observaciones": observacion.strip()
            }
        )

    # VENTA DIRECTA and ACOMPAÑAMIENTO both require a valid route
    if not matched_route:
        return ValidationResult(
            is_valid=False,
            error_code="MISSING_ROUTE",
            message="Es necesario especificar una ruta válida para esta modalidad."
        )

    route_day = matched_route.get("DIA", "").strip()
    if not route_day:
        return ValidationResult(
            is_valid=False,
            error_code="INVALID_ROUTE_DAY",
            message=f"La ruta {matched_route.get('RUTA')} no tiene un día asignado en el maestro."
        )

    # Route vs Day validation
    if route_day != target_weekday_code:
        return ValidationResult(
            is_valid=False,
            error_code="ROUTE_DAY_MISMATCH",
            message=(
                f"La ruta {matched_route.get('RUTA')} corresponde a los días {route_day}, "
                f"pero el día de trabajo operacional es {target_weekday_code}."
            )
        )

    if modalidad == Modality.VENTA_DIRECTA:
        return ValidationResult(
            is_valid=True,
            message="Modalidad Venta Directa válida",
            validated_data={
                "modalidad": Modality.VENTA_DIRECTA.value,
                "vendedor_apoyo": "VENTA DIRECTA",
                "codigo_erp_vendedor": "N/A",
                "ruta_oficial": matched_route.get("RUTA"),
                "zona": matched_route.get("ZONA", "N/A"),
                "codigo_ruta": str(matched_route.get("CODIGO RUTA", "N/A")),
                "dia": route_day,
                "observaciones": observacion.strip()
            }
        )

    if modalidad == Modality.ACOMPANAMIENTO:
        if not matched_seller:
            return ValidationResult(
                is_valid=False,
                error_code="MISSING_SELLER",
                message="La modalidad Acompañamiento requiere especificar un vendedor de apoyo válido."
            )

        return ValidationResult(
            is_valid=True,
            message="Modalidad Acompañamiento válida",
            validated_data={
                "modalidad": Modality.ACOMPANAMIENTO.value,
                "vendedor_apoyo": matched_seller.get("VENDEDOR"),
                "codigo_erp_vendedor": str(matched_seller.get("CODIGO ERP", "N/A")),
                "ruta_oficial": matched_route.get("RUTA"),
                "zona": matched_route.get("ZONA", "N/A"),
                "codigo_ruta": str(matched_route.get("CODIGO RUTA", "N/A")),
                "dia": route_day,
                "observaciones": observacion.strip()
            }
        )

    return ValidationResult(
        is_valid=False,
        error_code="UNKNOWN_MODALITY",
        message=f"Modalidad no reconocida: {modalidad}"
    )
