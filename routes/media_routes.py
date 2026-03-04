from flask import Blueprint, Response, abort

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
