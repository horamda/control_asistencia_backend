from functools import wraps

from flask import g, jsonify, request

from utils.jwt import verificar_token


def mobile_auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth_header = (request.headers.get("Authorization") or "").strip()
        if not auth_header.lower().startswith("bearer "):
            return jsonify({"error": "Authorization Bearer requerido"}), 401

        token = auth_header[7:].strip()
        if not token:
            return jsonify({"error": "Token requerido"}), 401

        try:
            payload = verificar_token(token)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 401

        empleado_id = payload.get("empleado_id") or payload.get("user_id")
        if not empleado_id:
            return jsonify({"error": "Token sin empleado_id"}), 401

        g.mobile_payload = payload
        g.mobile_empleado_id = int(empleado_id)
        return view(*args, **kwargs)

    return wrapped
