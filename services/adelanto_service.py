"""
Business logic for adelantos solicitados desde mobile.

Regla principal:
- un empleado solo puede solicitar un adelanto por mes calendario.
"""

import datetime

from repositories.adelanto_repository import create, get_by_empleado_periodo, get_by_id, update_estado
from repositories.empleado_repository import get_by_id as get_empleado_by_id


class AdelantoAlreadyRequestedError(ValueError):
    pass


def _parse_fecha_solicitud(fecha_solicitud: str | None) -> datetime.date:
    raw = str(fecha_solicitud or "").strip()
    if not raw:
        return datetime.date.today()
    return datetime.date.fromisoformat(raw)


def _is_duplicate_period_error(exc: Exception) -> bool:
    if getattr(exc, "errno", None) == 1062:
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and getattr(orig, "errno", None) == 1062:
        return True
    text = str(exc)
    return "Duplicate entry" in text or "uk_adelantos_empleado_periodo" in text


def get_adelanto_mes_actual(empleado_id: int, *, fecha_solicitud: str | None = None):
    fecha = _parse_fecha_solicitud(fecha_solicitud)
    return get_by_empleado_periodo(empleado_id, fecha.year, fecha.month)


def _require_record(adelanto_id: int) -> dict:
    record = get_by_id(adelanto_id)
    if not record:
        raise ValueError("Adelanto no encontrado.")
    return record


def solicitar_adelanto(
    *,
    empleado_id: int,
    empresa_id: int | None = None,
    fecha_solicitud: str | None = None,
) -> int:
    if not empleado_id:
        raise ValueError("Empleado es requerido.")

    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        raise ValueError("Empleado no encontrado.")

    fecha = _parse_fecha_solicitud(fecha_solicitud)
    periodo_year = fecha.year
    periodo_month = fecha.month

    existente = get_by_empleado_periodo(empleado_id, periodo_year, periodo_month)
    if existente:
        raise AdelantoAlreadyRequestedError("Ya solicitaste un adelanto en este mes.")

    resolved_empresa_id = empresa_id or empleado.get("empresa_id")
    if not resolved_empresa_id:
        raise ValueError("Empleado invalido o sin empresa asignada.")

    try:
        return create(
            {
                "empresa_id": resolved_empresa_id,
                "empleado_id": empleado_id,
                "periodo_year": periodo_year,
                "periodo_month": periodo_month,
                "fecha_solicitud": fecha.isoformat(),
                "estado": "pendiente",
            }
        )
    except Exception as exc:
        if _is_duplicate_period_error(exc):
            raise AdelantoAlreadyRequestedError("Ya solicitaste un adelanto en este mes.") from exc
        raise


def aprobar_adelanto(adelanto_id: int, *, actor_id: int | None = None) -> None:
    current = _require_record(adelanto_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if estado_actual != "pendiente":
        raise ValueError(
            f"No se puede aprobar un adelanto en estado '{estado_actual}'."
        )
    update_estado(adelanto_id, "aprobado", resuelto_by_usuario_id=actor_id)


def rechazar_adelanto(adelanto_id: int, *, actor_id: int | None = None) -> None:
    current = _require_record(adelanto_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if estado_actual != "pendiente":
        raise ValueError(
            f"No se puede rechazar un adelanto en estado '{estado_actual}'."
        )
    update_estado(adelanto_id, "rechazado", resuelto_by_usuario_id=actor_id)
