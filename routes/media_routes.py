from flask import Blueprint, Response, abort, request, send_file, session

from repositories.legajo_adjunto_repository import get_adjunto_by_id
from repositories.roles_repository import has_any_role
from services.legajo_attachment_service import resolve_legajo_storage_path
from services.profile_photo_service import get_profile_photo_bytes_by_dni

media_bp = Blueprint("media", __name__, url_prefix="/media")


def _sanitize_dni(raw: str):
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


@media_bp.route("/empleados/foto/<dni>", methods=["GET"])
def empleado_foto(dni):
    safe_dni = _sanitize_dni(dni)
    if not safe_dni:
        abort(404)

    payload = get_profile_photo_bytes_by_dni(safe_dni)
    if not payload or not payload.get("data"):
        abort(404)

    response = Response(
        payload["data"],
        mimetype=payload.get("mime_type") or "application/octet-stream",
    )
    response.headers["Cache-Control"] = "public, max-age=86400"
    updated_at = payload.get("updated_at")
    if updated_at is not None:
        response.headers["ETag"] = f'"{safe_dni}-{int(updated_at.timestamp())}"'
    return response


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
    if str(row.get("storage_backend") or "").lower() != "local":
        abort(404)

    try:
        path = resolve_legajo_storage_path(row.get("storage_ruta"))
    except RuntimeError:
        abort(404)
    if not path.exists() or not path.is_file():
        abort(404)

    download = str(request.args.get("download") or "").strip().lower() in {"1", "true", "yes"}
    return send_file(
        str(path),
        mimetype=row.get("mime_type") or "application/octet-stream",
        as_attachment=download,
        download_name=row.get("nombre_original") or path.name,
        max_age=86400,
    )
