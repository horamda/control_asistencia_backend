from flask import Blueprint, current_app, jsonify, request

from services.auth_service import authenticate_user
from services.profile_photo_service import get_profile_photo_version_by_dni
from utils.jwt import generar_token

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _imagen_version_safe(dni):
    try:
        return get_profile_photo_version_by_dni(dni)
    except Exception:
        current_app.logger.warning(
            "auth_login_imagen_version_error",
            extra={"extra": {"dni": dni}},
        )
        return None


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json

    dni = data.get("dni")
    password = data.get("password")

    if not dni or not password:
        return jsonify({"error": "DNI y contraseña requeridos"}), 400

    user, error = authenticate_user(dni, password)

    if error:
        return jsonify({"error": error}), 401

    payload = {
        "user_id": user["id"],
        "dni": user["dni"],
        "nombre": user["nombre"]
    }

    token = generar_token(payload)

    return jsonify({
        "token": token,
        "user": {
            "id": user["id"],
            "dni": user["dni"],
            "nombre": user["nombre"],
            "imagen_version": _imagen_version_safe(user.get("dni")),
        }
    })
