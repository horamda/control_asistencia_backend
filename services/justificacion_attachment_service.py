import datetime

from repositories.asistencia_repository import get_by_id as get_asistencia_by_id
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.justificacion_repository import get_by_id as get_justificacion_by_id
from repositories.legajo_adjunto_repository import (
    create_adjunto,
    get_adjunto_by_id,
    get_adjuntos_by_evento,
    mark_deleted,
)
from repositories.legajo_evento_repository import (
    create_evento,
    clear_justificacion_id,
    get_evento_by_justificacion_id,
    get_tipo_evento_by_codigo,
    update_evento,
    anular_evento,
)
from services.legajo_attachment_service import (
    resolve_legajo_storage_path,
    save_legajo_attachment_local,
)

JUSTIFICACION_EVENTO_CODIGO = "justificacion"
JUSTIFICACION_EVENTO_TITULO = "Justificacion de asistencia"


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _get_tipo_evento_id() -> int:
    tipo = get_tipo_evento_by_codigo(JUSTIFICACION_EVENTO_CODIGO)
    if not tipo:
        tipo = get_tipo_evento_by_codigo("otro")
    if not tipo:
        raise ValueError("No existe un tipo de legajo para justificaciones.")
    return int(tipo["id"])


def _resolve_fecha_evento(justificacion: dict) -> str:
    if justificacion.get("asistencia_id"):
        asistencia = get_asistencia_by_id(int(justificacion["asistencia_id"]))
        if asistencia and asistencia.get("fecha"):
            fecha = _to_date(asistencia.get("fecha"))
            if fecha:
                return fecha.isoformat()

    created_at = justificacion.get("created_at")
    fecha = _to_date(created_at)
    if fecha:
        return fecha.isoformat()
    return datetime.date.today().isoformat()


def _build_event_payload(justificacion: dict, *, actor_id: int | None):
    return {
        "empresa_id": int(justificacion["empresa_id"]),
        "empleado_id": int(justificacion["empleado_id"]),
        "tipo_id": _get_tipo_evento_id(),
        "fecha_evento": _resolve_fecha_evento(justificacion),
        "fecha_desde": None,
        "fecha_hasta": None,
        "titulo": JUSTIFICACION_EVENTO_TITULO,
        "descripcion": justificacion.get("motivo") or JUSTIFICACION_EVENTO_TITULO,
        "severidad": None,
        "justificacion_id": int(justificacion["id"]),
        "created_by_usuario_id": actor_id,
        "updated_by_usuario_id": actor_id,
    }


def _cleanup_saved_storage(saved: dict):
    backend = str(saved.get("storage_backend") or "").strip().lower()
    if backend != "local":
        return
    storage_ruta = str(saved.get("storage_ruta") or "").strip()
    if not storage_ruta:
        return
    try:
        path = resolve_legajo_storage_path(storage_ruta)
    except RuntimeError:
        return
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass


def get_or_create_justificacion_event(justificacion_id: int, *, actor_id: int | None = None) -> dict:
    justificacion = get_justificacion_by_id(justificacion_id)
    if not justificacion:
        raise ValueError("Justificacion no encontrada.")

    empleado = get_empleado_by_id(int(justificacion["empleado_id"]))
    if not empleado:
        raise ValueError("El empleado seleccionado no existe.")

    payload = _build_event_payload(
        {
            **justificacion,
            "empresa_id": empleado.get("empresa_id"),
        },
        actor_id=actor_id,
    )
    current = get_evento_by_justificacion_id(justificacion_id)
    if current:
        update_evento(int(current["id"]), payload)
        refreshed = get_evento_by_justificacion_id(justificacion_id)
        return refreshed or current

    event_id = create_evento(payload)
    refreshed = get_evento_by_justificacion_id(justificacion_id)
    if refreshed:
        return refreshed
    return {"id": event_id, **payload}


def sync_justificacion_event(justificacion_id: int, *, actor_id: int | None = None) -> dict:
    return get_or_create_justificacion_event(justificacion_id, actor_id=actor_id)


def list_justificacion_adjuntos(justificacion_id: int) -> list[dict]:
    evento = get_evento_by_justificacion_id(justificacion_id)
    if not evento:
        return []
    return get_adjuntos_by_evento(int(evento["id"]), include_deleted=False)


def justificacion_adjunto_to_mobile_dict(row: dict, justificacion_id: int) -> dict:
    adjunto_id = row.get("id")
    return {
        "id": adjunto_id,
        "evento_id": row.get("evento_id"),
        "nombre_original": row.get("nombre_original") or "",
        "mime_type": row.get("mime_type") or "application/octet-stream",
        "extension": row.get("extension"),
        "tamano_bytes": int(row.get("tamano_bytes") or 0),
        "estado": row.get("estado") or "activo",
        "created_at": (
            row.get("created_at").isoformat()
            if hasattr(row.get("created_at"), "isoformat")
            else str(row.get("created_at") or "")
        ),
        "download_url": f"/api/v1/mobile/me/justificaciones/{justificacion_id}/adjuntos/{adjunto_id}",
    }


def save_justificacion_adjuntos(
    justificacion_id: int,
    archivos,
    *,
    actor_id: int | None = None,
) -> list[dict]:
    archivos_validos = [
        file_storage
        for file_storage in archivos
        if file_storage and str(file_storage.filename or "").strip()
    ]
    if not archivos_validos:
        return []

    justificacion = get_justificacion_by_id(justificacion_id)
    if not justificacion:
        raise ValueError("Justificacion no encontrada.")

    empleado = get_empleado_by_id(int(justificacion["empleado_id"]))
    if not empleado:
        raise ValueError("El empleado seleccionado no existe.")

    evento = get_or_create_justificacion_event(justificacion_id, actor_id=actor_id)
    existing_rows = get_adjuntos_by_evento(int(evento["id"]), include_deleted=False)
    existing_sha256 = {
        str(row.get("sha256") or "").strip()
        for row in existing_rows
        if str(row.get("sha256") or "").strip()
    }

    created_rows: list[dict] = []
    for file_storage in archivos_validos:
        saved = save_legajo_attachment_local(
            file_storage,
            empresa_id=int(empleado["empresa_id"]),
            empleado_id=int(empleado["id"]),
            evento_id=int(evento["id"]),
        )
        if str(saved.get("sha256") or "").strip() in existing_sha256:
            _cleanup_saved_storage(saved)
            continue

        adjunto_id = create_adjunto(
            {
                "evento_id": int(evento["id"]),
                "empresa_id": int(empleado["empresa_id"]),
                "empleado_id": int(empleado["id"]),
                "nombre_original": saved["nombre_original"],
                "mime_type": saved["mime_type"],
                "extension": saved["extension"],
                "tamano_bytes": saved["tamano_bytes"],
                "sha256": saved["sha256"],
                "storage_backend": saved["storage_backend"],
                "storage_ruta": saved["storage_ruta"],
                "storage_data": saved.get("storage_data"),
                "created_by_usuario_id": actor_id,
            }
        )
        existing_sha256.add(str(saved.get("sha256") or "").strip())
        row = get_adjunto_by_id(int(adjunto_id))
        if row:
            created_rows.append(row)

    return created_rows


def delete_justificacion_resources(justificacion_id: int, *, actor_id: int | None = None) -> None:
    evento = get_evento_by_justificacion_id(justificacion_id)
    if not evento:
        clear_justificacion_id(justificacion_id, actor_id)
        return

    adjuntos = get_adjuntos_by_evento(int(evento["id"]), include_deleted=False)
    for adjunto in adjuntos:
        mark_deleted(int(adjunto["id"]), actor_id)
        _cleanup_saved_storage(adjunto)

    if str(evento.get("estado") or "").strip().lower() != "anulado":
        anular_evento(int(evento["id"]), actor_id, "Justificacion eliminada")
    clear_justificacion_id(justificacion_id, actor_id)
