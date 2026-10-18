"""Vacaciones por semanas y "Mi equipo" (jefes y duenos). Empleado y empresa salen siempre del token.
Contrato: docs/vacaciones_mobile.md y docs/mobile_v1_openapi.yaml (tag Vacaciones)."""

from flask import Blueprint, g, jsonify, request
from mysql.connector import ProgrammingError

from services import vacaciones_semanas_service as s
from utils.jwt_guard import mobile_auth_required

mobile = Blueprint("vacaciones_semanas_mobile", __name__, url_prefix="/api/v1/mobile/me")


@mobile.errorhandler(s.Error)
def invalido(error):
    status = getattr(error, "status", None) or (409 if isinstance(error, s.SaldoError) else 400)
    return jsonify(error=str(error)), status


@mobile.errorhandler(ProgrammingError)
def sin_migrar(error):
    if error.errno not in (1146, 1054):
        raise error
    return jsonify(error="Las vacaciones por semanas todavía no están disponibles."), 503


def _yo():
    return int(g.mobile_empleado_id)


def _cuerpo():
    datos = request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        raise s.Error("Envíe un objeto JSON.")
    return datos


# --- Empleado -----------------------------------------------------------------------------------------------

@mobile.get("/vacaciones/semanas")
@mobile_auth_required
def semanas():
    """Calendario de semanas del anio (?anio=, por defecto el actual) con su estado y el saldo en semanas."""
    return jsonify(s.semanas(_yo(), request.args.get("anio", type=int)))


@mobile.post("/vacaciones/semanas")
@mobile_auth_required
def pedir_semanas():
    """{"semanas": ["2026-12-07", "2026-12-14", "2027-01-11"], "observaciones": "..."}: una solicitud."""
    datos = _cuerpo()
    return jsonify(s.crear_solicitud(_yo(), datos.get("semanas"), datos.get("observaciones"))), 201


@mobile.get("/vacaciones/solicitudes")
@mobile_auth_required
def mis_solicitudes():
    return jsonify(s.mis_solicitudes(_yo(), request.args.get("anio", type=int)))


@mobile.get("/vacaciones/solicitudes/<int:solicitud_id>")
@mobile_auth_required
def mi_solicitud(solicitud_id):
    return jsonify(s.mi_solicitud(_yo(), solicitud_id))


@mobile.post("/vacaciones/solicitudes/<int:solicitud_id>/cancelar")
@mobile_auth_required
def cancelar(solicitud_id):
    """Pendiente: se cancela. Aprobada sin empezar: queda pedida la cancelacion para el jefe o RR. HH."""
    datos = _cuerpo()
    return jsonify(s.cancelar(_yo(), solicitud_id, datos.get("motivo"), movimiento_id=datos.get("movimiento_id")))


# --- Mi equipo (jefe directo y su cadena; duenos: toda la empresa) ---------------------------------------------

@mobile.get("/equipo/vacaciones")
@mobile_auth_required
def equipo():
    """?estado=pendiente|aprobada|rechazada|cancelada|parcial&anio="""
    return jsonify(s.equipo_solicitudes(_yo(), request.args.get("anio", type=int), request.args.get("estado") or None))


@mobile.get("/equipo/vacaciones/calendario")
@mobile_auth_required
def equipo_calendario():
    return jsonify(s.equipo_calendario(_yo(), request.args.get("mes")))


@mobile.get("/equipo/vacaciones/saldos")
@mobile_auth_required
def equipo_saldos():
    return jsonify(s.equipo_saldos(_yo(), request.args.get("anio", type=int)))


@mobile.get("/equipo/vacaciones/solicitudes/<int:solicitud_id>")
@mobile_auth_required
def equipo_solicitud(solicitud_id):
    return jsonify(s.equipo_solicitud(_yo(), solicitud_id))


@mobile.post("/equipo/vacaciones/solicitudes/<int:solicitud_id>/aprobar")
@mobile_auth_required
def aprobar(solicitud_id):
    return jsonify(s.aprobar(_yo(), solicitud_id))


@mobile.post("/equipo/vacaciones/solicitudes/<int:solicitud_id>/rechazar")
@mobile_auth_required
def rechazar(solicitud_id):
    return jsonify(s.rechazar(_yo(), solicitud_id, _cuerpo().get("motivo")))


@mobile.post("/equipo/vacaciones/solicitudes/<int:solicitud_id>/cancelacion/aprobar")
@mobile_auth_required
def aprobar_cancelacion(solicitud_id):
    return jsonify(s.resolver_cancelacion(_yo(), solicitud_id, True))


@mobile.post("/equipo/vacaciones/solicitudes/<int:solicitud_id>/cancelacion/rechazar")
@mobile_auth_required
def rechazar_cancelacion(solicitud_id):
    return jsonify(s.resolver_cancelacion(_yo(), solicitud_id, False, _cuerpo().get("motivo")))
