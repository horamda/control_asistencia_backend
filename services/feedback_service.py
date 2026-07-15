from __future__ import annotations

import datetime as _dt

from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.feedback_cliente_repository import get_by_id as get_cliente_by_id
from repositories.feedback_motivo_repository import get_by_id as get_motivo_by_id
from repositories.feedback_repository import (
    count_active_empleados,
    count_feedbacks,
    create as create_feedback_row,
    get_by_id,
    get_page,
    get_ranking_carga,
    get_top_motivos,
    update_estado,
)


def _fmt_dt(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ", timespec="minutes")
        except TypeError:
            return value.isoformat()
    return str(value)


def _fmt_date(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _feedback_estado_actual(row: dict) -> str:
    estado = str(row.get("estado_actual") or row.get("estado") or "").strip().lower()
    if estado in {"pendiente", "en_proceso", "resuelto", "vencido"}:
        return estado
    return "pendiente"


def serialize_feedback(row: dict) -> dict:
    if not row:
        return {}
    estado_actual = _feedback_estado_actual(row)
    resuelto = estado_actual == "resuelto"
    return {
        "id": row.get("id"),
        "empresa_id": row.get("empresa_id"),
        "estado": row.get("estado"),
        "estado_actual": estado_actual,
        "descripcion": row.get("descripcion"),
        "fecha_vencimiento": _fmt_date(row.get("fecha_vencimiento")),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
        "resuelto_at": _fmt_dt(row.get("resuelto_at")),
        "resuelto_en_sla": bool(row.get("resuelto_en_sla")) if resuelto else None,
        "resolucion_descripcion": row.get("resolucion_descripcion"),
        "dias_restantes": row.get("dias_restantes"),
        "empleado": {
            "id": row.get("empleado_id"),
            "nombre": row.get("empleado_nombre"),
            "legajo": row.get("empleado_legajo"),
            "dni": row.get("empleado_dni"),
            "activo": bool(row.get("empleado_activo")),
            "sector_id": row.get("empleado_sector_id"),
            "sector_nombre": row.get("empleado_sector_nombre"),
            "sucursal_id": row.get("empleado_sucursal_id"),
            "sucursal_nombre": row.get("empleado_sucursal_nombre"),
        },
        "jefe_directo": {
            "id": row.get("jefe_directo_id"),
            "nombre": row.get("jefe_directo_nombre"),
            "legajo": row.get("jefe_directo_legajo"),
            "dni": row.get("jefe_directo_dni"),
        },
        "cliente": {
            "id": row.get("cliente_id"),
            "codigo": row.get("cliente_codigo") or row.get("cliente_codigo_snapshot"),
            "razon_social": row.get("cliente_razon_social") or row.get("cliente_razon_social_snapshot"),
            "nombre_fantasia": row.get("cliente_nombre_fantasia") or row.get("cliente_nombre_fantasia_snapshot"),
            "tipo": row.get("cliente_tipo") or row.get("cliente_tipo_snapshot"),
        },
        "motivo": {
            "id": row.get("motivo_id"),
            "nombre": row.get("motivo_nombre") or row.get("motivo_nombre_snapshot"),
        },
        "resuelto_por": {
            "id": row.get("resuelto_por_empleado_id"),
            "nombre": row.get("resuelto_por_nombre"),
            "legajo": row.get("resuelto_por_legajo"),
        } if row.get("resuelto_por_empleado_id") else None,
    }


def _require_feedback(feedback_id: int) -> dict:
    record = get_by_id(feedback_id)
    if not record:
        raise ValueError("Feedback no encontrado.")
    return record


def _require_empleado_activo(empleado_id: int) -> dict:
    empleado = get_empleado_by_id(empleado_id)
    if not empleado or not empleado.get("activo"):
        raise ValueError("Empleado no encontrado o inactivo.")
    return empleado


def _require_jefe_directo(empleado: dict) -> dict:
    jefe_id = int(empleado.get("reporta_a_empleado_id") or 0)
    if jefe_id <= 0:
        raise ValueError("El empleado no tiene jefe directo asignado.")
    jefe = get_empleado_by_id(jefe_id)
    if not jefe or not jefe.get("activo"):
        raise ValueError("El jefe directo no esta disponible.")
    return jefe


def _require_cliente(cliente_id: int) -> dict:
    cliente = get_cliente_by_id(cliente_id)
    if not cliente or not cliente.get("activo"):
        raise ValueError("Cliente no encontrado o inactivo.")
    return cliente


def _require_motivo(motivo_id: int) -> dict:
    motivo = get_motivo_by_id(motivo_id)
    if not motivo or not motivo.get("activo"):
        raise ValueError("Motivo no encontrado o inactivo.")
    if int(motivo.get("sla_dias") or 0) <= 0:
        raise ValueError("El SLA del motivo debe ser mayor a cero.")
    return motivo


def create_feedback(
    *,
    empleado_id: int,
    cliente_id: int,
    motivo_id: int,
    descripcion: str,
) -> int:
    if not empleado_id:
        raise ValueError("Empleado es requerido.")
    if not cliente_id:
        raise ValueError("Cliente es requerido.")
    if not motivo_id:
        raise ValueError("Motivo es requerido.")

    descripcion = str(descripcion or "").strip()
    if not descripcion:
        raise ValueError("La descripcion es obligatoria.")

    empleado = _require_empleado_activo(int(empleado_id))
    jefe_directo = _require_jefe_directo(empleado)
    cliente = _require_cliente(int(cliente_id))
    motivo = _require_motivo(int(motivo_id))

    fecha_vencimiento = (_dt.date.today() + _dt.timedelta(days=int(motivo.get("sla_dias") or 1))).isoformat()

    return create_feedback_row(
        {
            "empresa_id": empleado.get("empresa_id"),
            "empleado_id": int(empleado_id),
            "jefe_directo_id": int(jefe_directo.get("id")),
            "cliente_id": int(cliente_id),
            "motivo_id": int(motivo_id),
            "descripcion": descripcion,
            "estado": "pendiente",
            "fecha_vencimiento": fecha_vencimiento,
            "cliente_codigo_snapshot": cliente.get("codigo_externo"),
            "cliente_razon_social_snapshot": cliente.get("razon_social"),
            "cliente_nombre_fantasia_snapshot": cliente.get("nombre_fantasia"),
            "cliente_tipo_snapshot": cliente.get("tipo_descripcion"),
            "motivo_nombre_snapshot": motivo.get("nombre"),
            "jefe_directo_nombre_snapshot": " ".join(
                part for part in [
                    str(jefe_directo.get("apellido") or "").strip(),
                    str(jefe_directo.get("nombre") or "").strip(),
                ]
                if part
            ) or None,
        }
    )


def tomar_feedback(feedback_id: int, *, actor_empleado_id: int) -> None:
    record = _require_feedback(feedback_id)
    if int(record.get("jefe_directo_id") or 0) != int(actor_empleado_id):
        raise ValueError("No tiene permisos para tomar este feedback.")
    if _feedback_estado_actual(record) == "resuelto":
        raise ValueError("El feedback ya fue resuelto.")
    update_estado(feedback_id, "en_proceso")


def resolver_feedback(
    feedback_id: int,
    *,
    actor_empleado_id: int,
    resolucion_descripcion: str,
) -> None:
    record = _require_feedback(feedback_id)
    if int(record.get("jefe_directo_id") or 0) != int(actor_empleado_id):
        raise ValueError("No tiene permisos para resolver este feedback.")
    estado_actual = _feedback_estado_actual(record)
    if estado_actual == "resuelto":
        raise ValueError("El feedback ya fue resuelto.")

    resolucion_descripcion = str(resolucion_descripcion or "").strip()
    if not resolucion_descripcion:
        raise ValueError("La descripcion de resolucion es obligatoria.")

    resuelto_at = _dt.datetime.now()
    fecha_vencimiento = record.get("fecha_vencimiento")
    if hasattr(fecha_vencimiento, "isoformat"):
        fecha_vencimiento_dt = fecha_vencimiento
    else:
        fecha_vencimiento_dt = _dt.date.fromisoformat(str(fecha_vencimiento))
    resuelto_en_sla = resuelto_at.date() <= fecha_vencimiento_dt
    update_estado(
        feedback_id,
        "resuelto",
        resuelto_at=resuelto_at,
        resuelto_por_empleado_id=actor_empleado_id,
        resolucion_descripcion=resolucion_descripcion,
        resuelto_en_sla=resuelto_en_sla,
    )


def get_feedback_historial(
    *,
    empleado_id: int,
    page: int = 1,
    per_page: int = 20,
    estado: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], int]:
    rows, total = get_page(
        page,
        per_page,
        empleado_id=empleado_id,
        estado=estado,
        search=search,
    )
    return [serialize_feedback(row) for row in rows], total


def get_feedback_bandeja(
    *,
    jefe_directo_id: int,
    page: int = 1,
    per_page: int = 20,
    estado: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], int]:
    rows, total = get_page(
        page,
        per_page,
        jefe_directo_id=jefe_directo_id,
        estado=estado,
        search=search,
    )
    return [serialize_feedback(row) for row in rows], total


def get_feedback_dashboard(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    sector_id: int | None = None,
    sucursal_id: int | None = None,
    empleado_activo: int | None = 1,
) -> dict:
    filters = {
        "empresa_id": empresa_id,
        "sector_id": sector_id,
        "sucursal_id": sucursal_id,
        "empleado_activo": empleado_activo,
    }
    resumen = count_feedbacks(**filters)
    top_motivos = get_top_motivos(**filters, limit=5)
    ranking_completo = get_ranking_carga(**filters, limit=None)
    ranking = ranking_completo[:10]
    total_activos = count_active_empleados(**filters)

    personal = None
    if empleado_id:
        propio_total = 0
        posicion = None
        for index, row in enumerate(ranking_completo, start=1):
            if int(row.get("empleado_id") or 0) == int(empleado_id):
                propio_total = int(row.get("total") or 0)
                posicion = index
                break
        if not propio_total:
            _, total_propios = get_page(
                1,
                1,
                empleado_id=empleado_id,
                empresa_id=empresa_id,
            )
            propio_total = int(total_propios or 0)
        total_feedbacks = int(resumen.get("total") or 0)
        promedio = round(total_feedbacks / total_activos, 2) if total_activos else 0.0
        personal = {
            "empleado_id": empleado_id,
            "total_cargados": propio_total,
            "posicion_ranking": posicion,
            "total_personal_activo": total_activos,
            "promedio_por_empleado": promedio,
            "porcentaje_sobre_total": round((propio_total * 100.0) / total_feedbacks, 1) if total_feedbacks else 0.0,
        }

    return {
        "resumen": resumen,
        "top_motivos": [
            {
                "motivo_id": row.get("motivo_id"),
                "motivo_nombre": row.get("motivo_nombre"),
                "total": int(row.get("total") or 0),
                "resueltos": int(row.get("resueltos") or 0),
            }
            for row in top_motivos
        ],
        "ranking": [
            {
                "empleado_id": row.get("empleado_id"),
                "legajo": row.get("legajo"),
                "apellido": row.get("apellido"),
                "nombre": row.get("nombre"),
                "total": int(row.get("total") or 0),
            }
            for row in ranking
        ],
        "personal": personal,
        "totales": {
            "empleados_activos": total_activos,
            "empleados_con_carga": resumen.get("empleados_con_carga", 0),
        },
    }
