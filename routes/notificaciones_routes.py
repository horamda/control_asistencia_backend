"""Bandeja de notificaciones de la app (campana). Empresa y empleado salen siempre del token.
Contrato: docs/notificaciones_mobile.md y docs/mobile_v1_openapi.yaml (/me/notificaciones)."""

from flask import Blueprint, jsonify, request
from mysql.connector import ProgrammingError

from routes.carga_routes import employee
from services import notificaciones_service as s
from utils.jwt_guard import mobile_auth_required

mobile = Blueprint("notificaciones_mobile", __name__, url_prefix="/api/v1/mobile/me/notificaciones")


@mobile.errorhandler(s.Error)
def invalido(error):
    return jsonify(error=str(error)), error.status


@mobile.errorhandler(ProgrammingError)
def sin_tabla(error):
    """Antes de correr la migracion: la bandeja responde vacia en vez de fallar."""
    if error.errno not in (1146, 1054):
        raise error
    return jsonify(error="La bandeja de notificaciones todavía no está disponible."), 503


def _cuerpo():
    return request.get_json(silent=True) or {}


@mobile.get("")
@mobile_auth_required
def listado():
    """No marca nada como leido."""
    args = request.args
    return jsonify(s.listado(employee(), args.get("estado"), args.get("modulo"), args.get("antes_de"), args.get("limite")))


@mobile.get("/resumen")
@mobile_auth_required
def resumen():
    return jsonify(s.resumen(employee()))


@mobile.get("/<int:notificacion_id>")
@mobile_auth_required
def detalle(notificacion_id):
    return jsonify(s.detalle(employee(), notificacion_id))


@mobile.post("/<int:notificacion_id>/leer")
@mobile_auth_required
def leer(notificacion_id):
    return jsonify(s.leer(employee(), notificacion_id))


@mobile.post("/leer-todas")
@mobile_auth_required
def leer_todas():
    datos = _cuerpo()
    return jsonify(s.leer_todas(employee(), datos.get("hasta_id"), datos.get("modulo")))
