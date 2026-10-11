"""
Finite State Machine (FSM) and state definitions for Supervisor Planner.
Enforces legal transitions and prevents invalid state mutations.
"""
from enum import Enum
from typing import Set, Dict


class PlanningStatus(str, Enum):
    PENDIENTE_ENVIO = "PENDIENTE_ENVIO"
    PENDIENTE_REVISION = "PENDIENTE_REVISION"
    PENDIENTE_CONFIRMACION = "PENDIENTE_CONFIRMACION"
    RECHAZADO = "RECHAZADO"
    PENDIENTE_CORRECCION = "PENDIENTE_CORRECCION"
    REGISTRADO = "REGISTRADO"
    MODIFICADO = "MODIFICADO"
    CANCELADO = "CANCELADO"
    EXENTO = "EXENTO"
    PENDIENTE_ESCALADO = "PENDIENTE_ESCALADO"


class InvalidStateTransitionError(ValueError):
    """Raised when an invalid state transition is attempted."""
    pass


# Map of allowed transitions: current_state -> set of allowed next states
ALLOWED_TRANSITIONS: Dict[PlanningStatus, Set[PlanningStatus]] = {
    PlanningStatus.PENDIENTE_ENVIO: {
        PlanningStatus.PENDIENTE_REVISION,
        PlanningStatus.PENDIENTE_CONFIRMACION,
        PlanningStatus.RECHAZADO,
        PlanningStatus.EXENTO,
        PlanningStatus.PENDIENTE_ESCALADO,
    },
    PlanningStatus.PENDIENTE_REVISION: {
        PlanningStatus.PENDIENTE_CONFIRMACION,
        PlanningStatus.RECHAZADO,
        PlanningStatus.PENDIENTE_CORRECCION,
        PlanningStatus.PENDIENTE_ESCALADO,
        PlanningStatus.CANCELADO,
    },
    PlanningStatus.PENDIENTE_CONFIRMACION: {
        PlanningStatus.REGISTRADO,
        PlanningStatus.MODIFICADO,
        PlanningStatus.PENDIENTE_CORRECCION,
        PlanningStatus.CANCELADO,
        PlanningStatus.PENDIENTE_ESCALADO,
    },
    PlanningStatus.RECHAZADO: {
        PlanningStatus.PENDIENTE_CORRECCION,
        PlanningStatus.PENDIENTE_CONFIRMACION,
        PlanningStatus.PENDIENTE_ESCALADO,
        PlanningStatus.CANCELADO,
    },
    PlanningStatus.PENDIENTE_CORRECCION: {
        PlanningStatus.PENDIENTE_CONFIRMACION,
        PlanningStatus.RECHAZADO,
        PlanningStatus.PENDIENTE_REVISION,
        PlanningStatus.PENDIENTE_ESCALADO,
        PlanningStatus.CANCELADO,
    },
    PlanningStatus.REGISTRADO: {
        PlanningStatus.PENDIENTE_CONFIRMACION,  # When requesting a modification
        PlanningStatus.CANCELADO,
    },
    PlanningStatus.MODIFICADO: {
        PlanningStatus.PENDIENTE_CONFIRMACION,  # When requesting another modification
        PlanningStatus.CANCELADO,
    },
    PlanningStatus.CANCELADO: {
        # Terminal state for the day
    },
    PlanningStatus.EXENTO: {
        # Terminal/administratively exempt state
    },
    PlanningStatus.PENDIENTE_ESCALADO: {
        PlanningStatus.PENDIENTE_CONFIRMACION,  # Late submission after cutoff
        PlanningStatus.CANCELADO,
        PlanningStatus.EXENTO,
    }
}


def validate_transition(current: PlanningStatus, target: PlanningStatus) -> bool:
    """
    Validates if transitioning from `current` to `target` is legally permitted.
    Raises InvalidStateTransitionError if illegal.
    """
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Transición ilegal de estado: no se puede pasar de {current.value} a {target.value}. "
            f"Transiciones permitidas desde {current.value}: {[s.value for s in allowed]}"
        )
    return True


def is_reminder_eligible(status: PlanningStatus) -> bool:
    """Returns True if the planning in this state should receive reminders."""
    return status in {
        PlanningStatus.PENDIENTE_ENVIO,
        PlanningStatus.PENDIENTE_CORRECCION,
        PlanningStatus.PENDIENTE_CONFIRMACION,
        PlanningStatus.PENDIENTE_REVISION,
    }


def is_terminal_status(status: PlanningStatus) -> bool:
    """Returns True if the status is finalized and should not change further."""
    return status in {
        PlanningStatus.REGISTRADO,
        PlanningStatus.MODIFICADO,
        PlanningStatus.CANCELADO,
        PlanningStatus.EXENTO
    }
