import hashlib

from flask import Blueprint, Response, abort, request, send_file, session

from repositories.legajo_adjunto_repository import get_adjunto_by_id, get_adjunto_data_by_id
from repositories.roles_repository import has_any_role
from services.legajo_attachment_service import resolve_legajo_storage_path
from services.profile_photo_service import get_profile_photo_bytes_by_dni

media_bp = Blueprint("media", __name__, url_prefix="/media")
public_media_bp = Blueprint("public_media", __name__)


def _sanitize_dni(raw: str):
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _photo_etag_token(safe_dni: str, payload: dict):
    updated_at = payload.get("updated_at")
    if updated_at is not None and hasattr(updated_at, "timestamp"):
        return f"{safe_dni}-{int(updated_at.timestamp())}"
    digest = hashlib.sha1(payload.get("data") or b"").hexdigest()[:16]
    return f"{safe_dni}-{digest}"


def _build_empleado_foto_response(dni: str):
    safe_dni = _sanitize_dni(dni)
    if not safe_dni:
        abort(404)

    payload = get_profile_photo_bytes_by_dni(safe_dni)
    if not payload or not payload.get("data"):
        abort(404)

    # El query param `v` se usa para cache busting del cliente, pero la fuente de verdad
    # para 304 es el ETag generado desde la foto real.
    _ = request.args.get("v")
    response = Response(
        payload["data"],
        mimetype=payload.get("mime_type") or "application/octet-stream",
    )
    response.headers["Cache-Control"] = "public, max-age=86400"
    etag_token = _photo_etag_token(safe_dni, payload)
    response.set_etag(etag_token)
    updated_at = payload.get("updated_at")
    if updated_at is not None:
        response.last_modified = updated_at
    response.make_conditional(request)
    return response


@media_bp.route("/empleados/foto/<dni>", methods=["GET"])
def empleado_foto(dni):
    return _build_empleado_foto_response(dni)


@public_media_bp.route("/empleados/imagen/<dni>", methods=["GET"])
def empleado_imagen(dni):
    return _build_empleado_foto_response(dni)


@media_bp.route("/legajos/adjunto/<int:adjunto_id>", methods=["GET"])
def legajo_adjunto(adjunto_id):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not has_any_role(user_id, ["admin", "rrhh", "supervisor"]):
        abort(403)

    row = get_adjunto_by_id(adjunto_id)
    if not row:
        abort(404)
    if str(row.get("estado") or "").lower() != "activo":
        abort(404)
    if str(row.get("evento_estado") or "").lower() != "vigente":
        abort(404)
    backend = str(row.get("storage_backend") or "").strip().lower()
    if backend not in {"local", "db"}:
        abort(404)

    download = str(request.args.get("download") or "").strip().lower() in {"1", "true", "yes"}
    if backend == "db":
        payload = get_adjunto_data_by_id(adjunto_id)
        if not payload:
            abort(404)
        response = Response(payload, mimetype=row.get("mime_type") or "application/octet-stream")
        response.headers["Cache-Control"] = "public, max-age=86400"
        if download:
            filename = str(row.get("nombre_original") or f"adjunto_{adjunto_id}.pdf").replace('"', "")
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    try:
        path = resolve_legajo_storage_path(row.get("storage_ruta"))
    except RuntimeError:
        abort(404)
    if not path.exists() or not path.is_file():
        abort(404)
    return send_file(
        str(path),
        mimetype=row.get("mime_type") or "application/octet-stream",
        as_attachment=download,
        download_name=row.get("nombre_original") or path.name,
        max_age=86400,
    )
