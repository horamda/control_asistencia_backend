from functools import wraps

from flask import g, jsonify, request

from utils.jwt import verificar_token

INVALID_SESSION_MESSAGE = "Sesion invalida o expirada."


def _unauthorized(message: str):
    response = jsonify({"error": message})
    response.headers["WWW-Authenticate"] = 'Bearer realm="mobile"'
    return response, 401


def mobile_auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth_header = (request.headers.get("Authorization") or "").strip()
        if not auth_header.lower().startswith("bearer "):
            return _unauthorized("Authorization Bearer requerido")

        token = auth_header[7:].strip()
        if not token:
            return _unauthorized("Authorization Bearer requerido")

        try:
            payload = verificar_token(token)
        except ValueError:
            return _unauthorized(INVALID_SESSION_MESSAGE)

        empleado_id = payload.get("empleado_id") or payload.get("user_id")
        if payload.get('type') == 'asistencia_qr' or isinstance(empleado_id, bool):
            return _unauthorized(INVALID_SESSION_MESSAGE)
        try:
            if not str(empleado_id).isascii() or not str(empleado_id).isdigit():
                raise ValueError()
            empleado_id = int(empleado_id)
            if empleado_id <= 0: raise ValueError()
        except (ValueError, TypeError):
            return _unauthorized(INVALID_SESSION_MESSAGE)

        g.mobile_payload = payload
        g.mobile_empleado_id = empleado_id
        return view(*args, **kwargs)

    return wrapped
