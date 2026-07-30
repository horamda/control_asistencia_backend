from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from uuid import uuid4

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
from repositories.sector_repository import get_by_id as get_sector_by_id
from werkzeug.utils import secure_filename


_EVIDENCIA_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_EVIDENCIA_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EVIDENCIA_MAX_BYTES = 8 * 1024 * 1024


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
    if estado == "resuelto":
        return estado
    if estado in {"pendiente", "en_proceso", "vencido"}:
        return "pendiente"
    return "pendiente"


def serialize_feedback(row: dict) -> dict:
    if not row:
        return {}
    estado_actual = _feedback_estado_actual(row)
    resuelto = estado_actual == "resuelto"
    return {
        "id": row.get("id"),
        "numero": row.get("numero") or (f"FB-{int(row.get('id')):08d}" if row.get("id") else None),
        "empresa_id": row.get("empresa_id"),
        "estado": row.get("estado"),
        "estado_actual": estado_actual,
        "condicion_temporal": row.get("condicion_temporal"),
        "descripcion": row.get("descripcion"),
        "fecha_vencimiento": _fmt_date(row.get("fecha_vencimiento")),
        "fecha_limite": _fmt_dt(row.get("fecha_limite")),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
        "resuelto_at": _fmt_dt(row.get("resuelto_at")),
        "resuelto_en_sla": bool(row.get("resuelto_en_sla")) if resuelto else None,
        "resolucion_descripcion": row.get("resolucion_descripcion"),
        "evidencia": {
            "filename": row.get("evidencia_filename"),
            "mime_type": row.get("evidencia_mime_type"),
            "size_bytes": row.get("evidencia_size_bytes"),
            "url": f"/media/feedback/evidencias/{row.get('id')}" if row.get("evidencia_path") else None,
        } if row.get("evidencia_path") else None,
        "dias_restantes": row.get("dias_restantes"),
        "minutos_restantes": row.get("minutos_restantes"),
        "sector_origen": {
            "id": row.get("sector_origen_id") or row.get("empleado_sector_id"),
            "nombre": row.get("sector_origen_nombre") or row.get("empleado_sector_nombre"),
        },
        "sucursal": {
            "id": row.get("sucursal_id") or row.get("empleado_sucursal_id"),
            "nombre": row.get("empleado_sucursal_nombre"),
        },
        "sector_responsable": {
            "id": row.get("sector_responsable_id"),
            "nombre": row.get("sector_responsable_nombre"),
        },
        "responsable": {
            "id": row.get("responsable_id") or row.get("jefe_directo_id"),
            "nombre": row.get("responsable_nombre") or row.get("jefe_directo_nombre"),
            "legajo": row.get("responsable_legajo") or row.get("jefe_directo_legajo"),
            "dni": row.get("responsable_dni") or row.get("jefe_directo_dni"),
        },
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


def _require_sector_responsable(motivo: dict) -> dict:
    sector_id = int(motivo.get("sector_id") or 0)
    if sector_id <= 0:
        raise ValueError("El motivo no tiene sector responsable asignado.")
    sector = get_sector_by_id(sector_id)
    if not sector or not sector.get("activo"):
        raise ValueError("El sector responsable del motivo no esta disponible.")
    responsable_id = int(sector.get("responsable_empleado_id") or motivo.get("sector_responsable_empleado_id") or 0)
    if responsable_id <= 0:
        raise ValueError("El sector responsable no tiene jefe asignado.")
    responsable = get_empleado_by_id(responsable_id)
    if not responsable or not responsable.get("activo"):
        raise ValueError("El responsable del sector no esta disponible.")
    return {"sector": sector, "responsable": responsable}


def _require_cliente(cliente_id: int) -> dict:
    cliente = get_cliente_by_id(cliente_id)
    if not cliente or not cliente.get("activo"):
        raise ValueError("Cliente no encontrado o inactivo.")
    return cliente


def _require_motivo(motivo_id: int) -> dict:
    motivo = get_motivo_by_id(motivo_id)
    if not motivo or not motivo.get("activo"):
        raise ValueError("Motivo no encontrado o inactivo.")
    if int(motivo.get("tiempo_resolucion_valor") or motivo.get("sla_dias") or 0) <= 0:
        raise ValueError("El tiempo de resolucion del motivo debe ser mayor a cero.")
    return motivo


def _feedback_due_datetime(motivo: dict, *, now: _dt.datetime | None = None) -> _dt.datetime:
    now = now or _dt.datetime.now()
    value = int(motivo.get("tiempo_resolucion_valor") or motivo.get("sla_dias") or 1)
    unit = str(motivo.get("tiempo_resolucion_unidad") or "DIAS").strip().upper()
    hours = value if unit == "HORAS" else value * 24
    return now + _dt.timedelta(hours=hours)


def _as_datetime(value) -> _dt.datetime | None:
    if not value:
        return None
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time(23, 59, 59))
    raw = str(value).strip()
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _feedback_evidencias_dir() -> Path:
    raw = str(os.getenv("FEEDBACK_EVIDENCIAS_DIR") or "uploads/feedback/evidencias").strip()
    base = Path(raw)
    if not base.is_absolute():
        base = Path.cwd() / base
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def resolve_feedback_evidencia_path(storage_path: str) -> Path:
    base = _feedback_evidencias_dir()
    candidate = (base / str(storage_path or "")).resolve()
    if base not in candidate.parents and candidate != base:
        raise RuntimeError("Ruta de evidencia invalida.")
    return candidate


def save_feedback_evidencia(file_storage) -> dict | None:
    if not file_storage or not str(file_storage.filename or "").strip():
        return None

    original_name = secure_filename(str(file_storage.filename or "evidencia"))
    suffix = Path(original_name).suffix.lower()
    mime_type = str(file_storage.mimetype or "").strip().lower()
    if suffix not in _EVIDENCIA_ALLOWED_EXTENSIONS or mime_type not in _EVIDENCIA_ALLOWED_MIME_TYPES:
        raise ValueError("La evidencia debe ser una imagen JPG, PNG o WebP.")

    stream = file_storage.stream
    stream.seek(0, os.SEEK_END)
    size_bytes = stream.tell()
    stream.seek(0)
    if size_bytes <= 0:
        raise ValueError("La evidencia esta vacia.")
    if size_bytes > _EVIDENCIA_MAX_BYTES:
        raise ValueError("La evidencia supera el maximo permitido de 8 MB.")

    storage_name = f"{uuid4().hex}{suffix}"
    destination = resolve_feedback_evidencia_path(storage_name)
    file_storage.save(destination)
    return {
        "evidencia_filename": original_name,
        "evidencia_path": storage_name,
        "evidencia_mime_type": mime_type,
        "evidencia_size_bytes": size_bytes,
    }


def create_feedback(
    *,
    empleado_id: int,
    cliente_id: int,
    motivo_id: int,
    descripcion: str,
    evidencia_file=None,
) -> int:
    if not empleado_id:
        raise ValueError("Empleado es requerido.")
    if not cliente_id:
        raise ValueError("Cliente es requerido.")
    if not motivo_id:
        raise ValueError("Motivo es requerido.")

    empleado = _require_empleado_activo(int(empleado_id))
    if not empleado.get("sector_id"):
        raise ValueError("El empleado no tiene sector asignado; no puede cargar feedback.")
    cliente = _require_cliente(int(cliente_id))
    motivo = _require_motivo(int(motivo_id))
    jefe_directo = _require_jefe_directo(empleado)
    asignacion = _require_sector_responsable(motivo)
    sector_responsable = asignacion["sector"]

    descripcion = str(descripcion or "").strip()
    if bool(motivo.get("requiere_observacion", True)) and not descripcion:
        raise ValueError("La descripcion es obligatoria para este motivo.")
    if bool(motivo.get("requiere_foto")) and not evidencia_file:
        raise ValueError("La evidencia fotografica es obligatoria para este motivo.")

    fecha_limite = _feedback_due_datetime(motivo)
    fecha_vencimiento = fecha_limite.date().isoformat()
    evidencia = save_feedback_evidencia(evidencia_file)

    return create_feedback_row(
        {
            "empresa_id": empleado.get("empresa_id"),
            "numero": None,
            "empleado_id": int(empleado_id),
            "sector_origen_id": empleado.get("sector_id"),
            "sucursal_id": empleado.get("sucursal_id"),
            "jefe_directo_id": int(jefe_directo.get("id")),
            "cliente_id": int(cliente_id),
            "motivo_id": int(motivo_id),
            "sector_responsable_id": int(sector_responsable.get("id")),
            "responsable_id": int(jefe_directo.get("id")),
            "descripcion": descripcion,
            "estado": "pendiente",
            "fecha_vencimiento": fecha_vencimiento,
            "fecha_limite": fecha_limite,
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
            **(evidencia or {}),
        }
    )


def tomar_feedback(feedback_id: int, *, actor_empleado_id: int) -> None:
    record = _require_feedback(feedback_id)
    if int(record.get("responsable_id") or record.get("jefe_directo_id") or 0) != int(actor_empleado_id):
        raise ValueError("No tiene permisos para tomar este feedback.")
    if _feedback_estado_actual(record) == "resuelto":
        raise ValueError("El feedback ya fue resuelto.")
    return None


def resolver_feedback(
    feedback_id: int,
    *,
    actor_empleado_id: int,
    resolucion_descripcion: str,
) -> None:
    record = _require_feedback(feedback_id)
    if int(record.get("responsable_id") or record.get("jefe_directo_id") or 0) != int(actor_empleado_id):
        raise ValueError("No tiene permisos para resolver este feedback.")
    estado_actual = _feedback_estado_actual(record)
    if estado_actual == "resuelto":
        raise ValueError("El feedback ya fue resuelto.")

    resolucion_descripcion = str(resolucion_descripcion or "").strip()
    if not resolucion_descripcion:
        raise ValueError("La descripcion de resolucion es obligatoria.")

    resuelto_at = _dt.datetime.now()
    fecha_limite = _as_datetime(record.get("fecha_limite"))
    if not fecha_limite:
        fecha_vencimiento = record.get("fecha_vencimiento")
        fecha_limite = _dt.datetime.combine(
            fecha_vencimiento if hasattr(fecha_vencimiento, "year") else _dt.date.fromisoformat(str(fecha_vencimiento)),
            _dt.time(23, 59, 59),
        )
    resuelto_en_sla = resuelto_at <= fecha_limite
    update_estado(
        feedback_id,
        "resuelto",
        resuelto_at=resuelto_at,
        resuelto_por_empleado_id=actor_empleado_id,
        resolucion_descripcion=resolucion_descripcion,
        resuelto_en_sla=resuelto_en_sla,
    )


def resolver_feedback_admin(
    feedback_id: int,
    *,
    actor_empleado_id: int | None,
    resolucion_descripcion: str,
) -> None:
    record = _require_feedback(feedback_id)
    estado_actual = _feedback_estado_actual(record)
    if estado_actual == "resuelto":
        raise ValueError("El feedback ya fue resuelto.")

    resolucion_descripcion = str(resolucion_descripcion or "").strip()
    if not resolucion_descripcion:
        raise ValueError("La descripcion de resolucion es obligatoria.")

    resuelto_at = _dt.datetime.now()
    fecha_limite = _as_datetime(record.get("fecha_limite"))
    if not fecha_limite:
        fecha_vencimiento = record.get("fecha_vencimiento")
        fecha_limite = _dt.datetime.combine(
            fecha_vencimiento if hasattr(fecha_vencimiento, "year") else _dt.date.fromisoformat(str(fecha_vencimiento)),
            _dt.time(23, 59, 59),
        )
    resuelto_en_sla = resuelto_at <= fecha_limite
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
    sector_origen_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
    estado: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], int]:
    rows, total = get_page(
        page,
        per_page,
        empleado_id=None if sector_origen_id else empleado_id,
        sector_origen_id=sector_origen_id,
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
        responsable_id=jefe_directo_id,
        estado=estado,
        search=search,
    )
    return [serialize_feedback(row) for row in rows], total


def get_feedback_dashboard(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    sector_id: int | None = None,
    sector_responsable_id: int | None = None,
    responsable_id: int | None = None,
    sucursal_id: int | None = None,
    empleado_activo: int | None = 1,
) -> dict:
    filters = {
        "empresa_id": empresa_id,
        "sector_id": sector_id,
        "sector_responsable_id": sector_responsable_id,
        "responsable_id": responsable_id,
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
