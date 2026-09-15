from flask import Blueprint, current_app, jsonify, make_response, render_template, request

from services.presencia_service import build_presence


presencia_bp = Blueprint("presencia", __name__, url_prefix="/presencia")


@presencia_bp.get("")
@presencia_bp.get("/")
def pantalla():
    response = make_response(render_template("presencia.html"))
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@presencia_bp.get("/datos")
def datos():
    raw = request.args.get("empresa_id", "")
    try:
        empresa_id = int(raw) if raw else None
        if empresa_id is not None and empresa_id <= 0:
            raise ValueError
    except ValueError:
        response = jsonify(error="Empresa inválida.")
        response.status_code = 400
    else:
        try:
            response = jsonify(build_presence(empresa_id))
        except Exception:
            current_app.logger.exception("presencia_consulta_error")
            response = jsonify(error="No se pudo actualizar la presencia. Reintentando en 30 segundos.")
            response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
