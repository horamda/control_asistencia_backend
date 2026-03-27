"""
Business logic for justificaciones.

State machine
─────────────
  pendiente ──► aprobada
  pendiente ──► rechazada
  aprobada  ──► pendiente   (admin revert)
  rechazada ──► pendiente   (admin revert / re-open)

All other transitions are rejected with ValueError.
"""

from repositories.asistencia_repository import get_by_id as get_asistencia_by_id
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.justificacion_repository import (
    create,
    get_by_asistencia,
    get_by_id,
    update,
    update_estado,
)

ESTADOS_VALIDOS: frozenset[str] = frozenset({"pendiente", "aprobada", "rechazada"})

# Maps current_estado → set of reachable next estados
VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "pendiente": frozenset({"aprobada", "rechazada"}),
    "aprobada":  frozenset({"pendiente"}),
    "rechazada": frozenset({"pendiente"}),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_fields(data: dict, current: dict | None = None) -> list[str]:
    """
    Validates justificacion data. Returns a list of human-readable errors.
    Pass `current` when updating an existing record (enables state-transition check).
    """
    errors: list[str] = []

    empleado_id: int | None = data.get("empleado_id")
    asistencia_id: int | None = data.get("asistencia_id")
    motivo: str = (data.get("motivo") or "").strip()
    estado: str = (data.get("estado") or "pendiente").strip()

    if not empleado_id:
        errors.append("Empleado es requerido.")

    if not motivo:
        errors.append("Motivo es requerido.")

    if estado not in ESTADOS_VALIDOS:
        errors.append(
            f"Estado invalido. Valores permitidos: {', '.join(sorted(ESTADOS_VALIDOS))}."
        )

    if errors:
        return errors  # no point running DB checks with broken base fields

    # FK: empleado must exist
    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        errors.append("El empleado seleccionado no existe.")
        return errors

    if asistencia_id:
        asistencia = get_asistencia_by_id(asistencia_id)
        if not asistencia:
            errors.append("La asistencia seleccionada no existe.")
        elif asistencia.get("empleado_id") != empleado_id:
            errors.append(
                "La asistencia seleccionada no pertenece al empleado indicado."
            )
        else:
            # Duplicate guard: only one justificacion per asistencia+empleado
            existentes = get_by_asistencia(asistencia_id)
            for j in existentes:
                if current and j["id"] == current["id"]:
                    continue  # same record being edited — not a duplicate
                if j["empleado_id"] == empleado_id:
                    errors.append(
                        "Ya existe una justificacion para esta asistencia y empleado."
                    )
                    break

    # State-transition guard (edit only)
    if current:
        estado_actual = (current.get("estado") or "pendiente").strip()
        if estado != estado_actual:
            allowed = VALID_TRANSITIONS.get(estado_actual, frozenset())
            if estado not in allowed:
                allowed_str = ", ".join(f"'{e}'" for e in sorted(allowed)) or "ninguna"
                errors.append(
                    f"Cambio de estado no permitido: '{estado_actual}' → '{estado}'. "
                    f"Transiciones validas: {allowed_str}."
                )

    return errors


def _require_record(justificacion_id: int) -> dict:
    record = get_by_id(justificacion_id)
    if not record:
        raise ValueError("Justificacion no encontrada.")
    return record


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_justificacion(data: dict) -> int:
    """
    Validates and creates a new justificacion.
    Returns the new record id.
    Raises ValueError with the first error found.
    """
    normalized = dict(data)
    if not normalized.get("estado"):
        normalized["estado"] = "pendiente"

    errors = _validate_fields(normalized)
    if errors:
        raise ValueError(errors[0])

    return create(normalized)


def update_justificacion(justificacion_id: int, data: dict) -> None:
    """
    Validates and updates a justificacion.
    Raises ValueError with the first error found.
    """
    current = _require_record(justificacion_id)

    normalized = dict(data)
    if not normalized.get("estado"):
        normalized["estado"] = current.get("estado") or "pendiente"

    errors = _validate_fields(normalized, current=current)
    if errors:
        raise ValueError(errors[0])

    update(justificacion_id, normalized)


def aprobar_justificacion(justificacion_id: int) -> None:
    """
    Transitions a justificacion to 'aprobada'.
    Only valid from 'pendiente'.
    Raises ValueError if the transition is not allowed.
    """
    current = _require_record(justificacion_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if "aprobada" not in VALID_TRANSITIONS.get(estado_actual, frozenset()):
        raise ValueError(
            f"No se puede aprobar una justificacion en estado '{estado_actual}'."
        )
    update_estado(justificacion_id, "aprobada")


def rechazar_justificacion(justificacion_id: int) -> None:
    """
    Transitions a justificacion to 'rechazada'.
    Only valid from 'pendiente'.
    Raises ValueError if the transition is not allowed.
    """
    current = _require_record(justificacion_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if "rechazada" not in VALID_TRANSITIONS.get(estado_actual, frozenset()):
        raise ValueError(
            f"No se puede rechazar una justificacion en estado '{estado_actual}'."
        )
    update_estado(justificacion_id, "rechazada")


def revertir_justificacion(justificacion_id: int) -> None:
    """
    Reverts an aprobada/rechazada justificacion back to 'pendiente'.
    Raises ValueError if the transition is not allowed.
    """
    current = _require_record(justificacion_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if "pendiente" not in VALID_TRANSITIONS.get(estado_actual, frozenset()):
        raise ValueError(
            f"No se puede revertir una justificacion en estado '{estado_actual}'."
        )
    update_estado(justificacion_id, "pendiente")
