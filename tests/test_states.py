"""
Unit tests for Planning State Machine (FSM) transitions.
"""
import pytest
from app.business.states import (
    PlanningStatus,
    validate_transition,
    InvalidStateTransitionError,
    is_reminder_eligible,
    is_terminal_status
)


def test_valid_transitions():
    """Verifica transiciones legales del ciclo de vida."""
    # Flujo nuevo
    assert validate_transition(PlanningStatus.PENDIENTE_ENVIO, PlanningStatus.PENDIENTE_CONFIRMACION) is True
    assert validate_transition(PlanningStatus.PENDIENTE_CONFIRMACION, PlanningStatus.REGISTRADO) is True
    
    # Flujo modificación
    assert validate_transition(PlanningStatus.REGISTRADO, PlanningStatus.PENDIENTE_CONFIRMACION) is True
    assert validate_transition(PlanningStatus.PENDIENTE_CONFIRMACION, PlanningStatus.MODIFICADO) is True

    # Flujo rechazo y corrección
    assert validate_transition(PlanningStatus.PENDIENTE_ENVIO, PlanningStatus.RECHAZADO) is True
    assert validate_transition(PlanningStatus.RECHAZADO, PlanningStatus.PENDIENTE_CORRECCION) is True
    assert validate_transition(PlanningStatus.PENDIENTE_CORRECCION, PlanningStatus.PENDIENTE_CONFIRMACION) is True

    # Flujo cancelación
    assert validate_transition(PlanningStatus.REGISTRADO, PlanningStatus.CANCELADO) is True


def test_invalid_transitions():
    """Verifica que transiciones ilegales generen InvalidStateTransitionError."""
    # No se puede pasar a REGISTRADO sin pasar por PENDIENTE_CONFIRMACION
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(PlanningStatus.PENDIENTE_ENVIO, PlanningStatus.REGISTRADO)

    # No se puede pasar de CANCELADO a REGISTRADO
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(PlanningStatus.CANCELADO, PlanningStatus.REGISTRADO)

    # No se puede pasar de REGISTRADO a PENDIENTE_ENVIO
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(PlanningStatus.REGISTRADO, PlanningStatus.PENDIENTE_ENVIO)


def test_reminder_eligibility():
    """Verifica qué estados son elegibles para recibir recordatorios cada 15 min."""
    assert is_reminder_eligible(PlanningStatus.PENDIENTE_ENVIO) is True
    assert is_reminder_eligible(PlanningStatus.PENDIENTE_CORRECCION) is True
    assert is_reminder_eligible(PlanningStatus.PENDIENTE_CONFIRMACION) is True
    
    assert is_reminder_eligible(PlanningStatus.REGISTRADO) is False
    assert is_reminder_eligible(PlanningStatus.MODIFICADO) is False
    assert is_reminder_eligible(PlanningStatus.CANCELADO) is False
    assert is_reminder_eligible(PlanningStatus.EXENTO) is False


def test_terminal_statuses():
    """Verifica estados terminales de la jornada."""
    assert is_terminal_status(PlanningStatus.REGISTRADO) is True
    assert is_terminal_status(PlanningStatus.MODIFICADO) is True
    assert is_terminal_status(PlanningStatus.CANCELADO) is True
    assert is_terminal_status(PlanningStatus.EXENTO) is True

    assert is_terminal_status(PlanningStatus.PENDIENTE_ENVIO) is False
    assert is_terminal_status(PlanningStatus.PENDIENTE_CONFIRMACION) is False
