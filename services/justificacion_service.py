"""
Business logic for justificaciones.

State machine
------------
  pendiente -> aprobada
  pendiente -> rechazada
  aprobada  -> pendiente   (admin revert)
  rechazada -> pendiente   (admin revert / re-open)

All other transitions are rejected with ValueError.
"""

import datetime as _dt

from repositories.asistencia_repository import get_by_id as get_asistencia_by_id
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.justificacion_repository import (
    create,
    get_by_asistencia,
    get_by_fecha,
    get_by_rango,
    get_by_id,
    update,
    update_estado,
)

ESTADOS_VALIDOS: frozenset[str] = frozenset({"pendiente", "aprobada", "rechazada"})

# Maps current_estado -> set of reachable next estados
VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "pendiente": frozenset({"aprobada", "rechazada"}),
    "aprobada": frozenset({"pendiente"}),
    "rechazada": frozenset({"pendiente"}),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(value) -> _dt.date | None:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _resolve_periodo(
    data: dict,
    *,
    current: dict | None = None,
    asistencia: dict | None = None,
):
    raw_fecha_desde = data.get("fecha_desde")
    raw_fecha_hasta = data.get("fecha_hasta")
    raw_fecha = data.get("fecha")

    fecha_desde = _parse_date(raw_fecha_desde)
    fecha_hasta = _parse_date(raw_fecha_hasta)
    fecha = _parse_date(raw_fecha)

    if raw_fecha_desde not in (None, "") and fecha_desde is None:
        return None, None, "Fecha desde invalida. Use formato YYYY-MM-DD."
    if raw_fecha_hasta not in (None, "") and fecha_hasta is None:
        return None, None, "Fecha hasta invalida. Use formato YYYY-MM-DD."
    if raw_fecha not in (None, "") and fecha is None:
        return None, None, "Fecha invalida. Use formato YYYY-MM-DD."

    asistencia_id = data.get("asistencia_id")
    if asistencia is None and asistencia_id:
        asistencia = get_asistencia_by_id(asistencia_id)

    current_desde = _parse_date(current.get("fecha_desde")) if current else None
    current_hasta = _parse_date(current.get("fecha_hasta")) if current else None
    current_fecha = _parse_date(current.get("fecha")) if current else None
    if current_desde is None:
        current_desde = current_fecha
    if current_hasta is None:
        current_hasta = current_fecha

    asistencia_fecha = _parse_date(asistencia.get("fecha")) if asistencia and asistencia.get("fecha") else None

    if fecha_desde is None and fecha_hasta is None:
        if fecha is not None:
            fecha_desde = fecha_hasta = fecha
        elif current_desde is not None or current_hasta is not None:
            fecha_desde = current_desde or current_hasta
            fecha_hasta = current_hasta or current_desde or fecha_desde
        elif asistencia_fecha is not None:
            fecha_desde = fecha_hasta = asistencia_fecha
        else:
            today = _dt.date.today()
            fecha_desde = fecha_hasta = today
    else:
        if fecha_desde is None:
            fecha_desde = fecha or current_desde or fecha_hasta
        if fecha_hasta is None:
            fecha_hasta = fecha or current_hasta or fecha_desde

    if fecha_desde is None or fecha_hasta is None:
        return None, None, "Fecha invalida. Use formato YYYY-MM-DD."

    if fecha_desde > fecha_hasta:
        return None, None, "La fecha desde no puede ser mayor que la fecha hasta."

    if fecha_desde > _dt.date.today() or fecha_hasta > _dt.date.today():
        return None, None, "Fecha no puede ser futura."

    return fecha_desde, fecha_hasta, None


def _resolve_fecha(
    data: dict,
    *,
    current: dict | None = None,
    asistencia: dict | None = None,
):
    fecha_desde, _, error = _resolve_periodo(data, current=current, asistencia=asistencia)
    return fecha_desde, error


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
    fecha_desde, fecha_hasta, fecha_error = _resolve_periodo(data, current=current)

    if not empleado_id:
        errors.append("Empleado es requerido.")

    if not motivo:
        errors.append("Motivo es requerido.")

    if estado not in ESTADOS_VALIDOS:
        errors.append(
            f"Estado invalido. Valores permitidos: {', '.join(sorted(ESTADOS_VALIDOS))}."
        )

    if fecha_error:
        errors.append(fecha_error)

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
        elif fecha_desde and fecha_hasta and fecha_desde != fecha_hasta:
            errors.append(
                "La asistencia seleccionada solo puede vincularse a una fecha unica."
            )
        else:
            asistencia_fecha = _parse_date(asistencia.get("fecha"))
            if asistencia_fecha and (fecha_desde != asistencia_fecha or fecha_hasta != asistencia_fecha):
                errors.append("La fecha debe coincidir con la asistencia seleccionada.")
                return errors
            # Duplicate guard: only one justificacion per asistencia+empleado
            existentes = get_by_asistencia(asistencia_id)
            for j in existentes:
                if current and j["id"] == current["id"]:
                    continue  # same record being edited - not a duplicate
                if j["empleado_id"] == empleado_id:
                    errors.append(
                        "Ya existe una justificacion para esta asistencia y empleado."
                    )
                    break

    if fecha_desde and fecha_hasta:
        if fecha_desde == fecha_hasta:
            existentes_fecha = get_by_fecha(empleado_id, fecha_desde.isoformat())
            for j in existentes_fecha:
                if current and j["id"] == current["id"]:
                    continue
                errors.append("Ya existe una justificacion para esta fecha y empleado.")
                break
        else:
            existentes_rango = get_by_rango(
                empleado_id,
                fecha_desde.isoformat(),
                fecha_hasta.isoformat(),
            )
            for j in existentes_rango:
                if current and j["id"] == current["id"]:
                    continue
                errors.append("Ya existe una justificacion que se superpone con el rango seleccionado.")
                break

    # State-transition guard (edit only)
    if current:
        estado_actual = (current.get("estado") or "pendiente").strip()
        if estado != estado_actual:
            allowed = VALID_TRANSITIONS.get(estado_actual, frozenset())
            if estado not in allowed:
                allowed_str = ", ".join(f"'{e}'" for e in sorted(allowed)) or "ninguna"
                errors.append(
                    f"Cambio de estado no permitido: '{estado_actual}' -> '{estado}'. "
                    f"Transiciones validas: {allowed_str}."
                )

    return errors


def _require_record(justificacion_id: int) -> dict:
    record = get_by_id(justificacion_id)
    if not record:
        raise ValueError("Justificacion no encontrada.")
    return record


def _normalize_fecha(data: dict, *, current: dict | None = None) -> str:
    fecha_desde, _, _ = _resolve_periodo(data, current=current)
    if fecha_desde is None:
        return _dt.date.today().isoformat()
    return fecha_desde.isoformat()


def _normalize_periodo(data: dict, *, current: dict | None = None) -> tuple[str, str]:
    fecha_desde, fecha_hasta, _ = _resolve_periodo(data, current=current)
    if fecha_desde is None or fecha_hasta is None:
        hoy = _dt.date.today().isoformat()
        return hoy, hoy
    return fecha_desde.isoformat(), fecha_hasta.isoformat()


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
    normalized["estado"] = "pendiente"

    if not normalized.get("fecha_desde"):
        raise ValueError("Fecha desde es requerida.")
    if not normalized.get("fecha_hasta"):
        raise ValueError("Fecha hasta es requerida.")

    errors = _validate_fields(normalized)
    if errors:
        raise ValueError(errors[0])

    fecha_desde, fecha_hasta = _normalize_periodo(normalized)
    normalized["fecha"] = fecha_desde
    normalized["fecha_desde"] = fecha_desde
    normalized["fecha_hasta"] = fecha_hasta
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

    fecha_desde, fecha_hasta = _normalize_periodo(normalized, current=current)
    normalized["fecha"] = fecha_desde
    normalized["fecha_desde"] = fecha_desde
    normalized["fecha_hasta"] = fecha_hasta
    update(justificacion_id, normalized)


def aprobar_justificacion(
    justificacion_id: int,
    *,
    actor_id: int | None = None,
    comentario_resolucion: str | None = None,
) -> None:
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
    update_estado(
        justificacion_id,
        "aprobada",
        resuelto_by_usuario_id=actor_id,
        comentario_resolucion=comentario_resolucion,
    )


def rechazar_justificacion(
    justificacion_id: int,
    *,
    actor_id: int | None = None,
    motivo_rechazo: str | None = None,
) -> None:
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
    motivo = str(motivo_rechazo or "").strip()
    if not motivo:
        raise ValueError("Motivo de rechazo es requerido.")
    update_estado(
        justificacion_id,
        "rechazada",
        resuelto_by_usuario_id=actor_id,
        motivo_rechazo=motivo,
    )


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
