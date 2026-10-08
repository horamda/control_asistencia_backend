"""Employee-owned reimbursement API; identity comes exclusively from the token."""

from decimal import Decimal
from flask import Blueprint, jsonify, request
from mysql.connector import IntegrityError, ProgrammingError
from routes.carga_routes import employee, private_photo, serialize as dates
from services import reintegro_service as service
from utils.jwt_guard import mobile_auth_required

reintegros_mobile_bp = Blueprint(
    "reintegros_mobile", __name__, url_prefix="/api/v1/mobile/reintegros"
)


def serialize(value):
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, dict):
        return {
            k: (
                v.strftime("%Y-%m")
                if k == "periodo" and hasattr(v, "strftime")
                else serialize(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [serialize(v) for v in value]
    return dates(value)


def actor(emp):
    return dict(mode="empleado", empresa_id=emp["empresa_id"], empleado_id=emp["id"])


def data():
    result = request.get_json(silent=True) if request.is_json else request.form
    if not hasattr(result, "get"):
        raise service.Error("Envíe un objeto JSON o multipart.")
    return result


@reintegros_mobile_bp.before_request
def limits():
    request.max_content_length = 27 * 1024 * 1024
    request.max_form_parts = 200


@reintegros_mobile_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@reintegros_mobile_bp.errorhandler(service.Error)
def invalid(error):
    return jsonify(error=str(error)), error.status


@reintegros_mobile_bp.errorhandler(IntegrityError)
def conflict(error):
    return jsonify(error="Conflicto de datos. Actualice la solicitud."), 409


@reintegros_mobile_bp.errorhandler(ProgrammingError)
def schema_unavailable(error):
    if error.errno != 1146:
        raise error
    return (
        jsonify(
            error="El módulo de reintegros todavía no está disponible. Contacte al administrador."
        ),
        503,
    )


@reintegros_mobile_bp.errorhandler(413)
def large(error):
    return jsonify(error="Máximo 27 MB por envío y 5 MB por foto."), 413


@reintegros_mobile_bp.get("/config")
@mobile_auth_required
def config():
    emp = employee()
    concepts = [c for c in service.categories(emp["empresa_id"]) if c["activo"]]
    return jsonify(
        serialize(
            dict(
                moneda="ARS",
                estados=service.STATES,
                categorias=concepts,
                conceptos=concepts,
                version_contrato="1.35.0",
                limites=dict(
                    gastos=50,
                    fotos_por_gasto=3,
                    bytes_foto=5 * 1024 * 1024,
                    bytes_envio=27 * 1024 * 1024,
                ),
                formatos_foto=["image/jpeg", "image/png", "image/webp"],
                mensual=service.monthly.configuration(emp),
                recordatorios=service.monthly.reminders(emp),
            )
        )
    )


@reintegros_mobile_bp.get("/solicitudes")
@mobile_auth_required
def history():
    return jsonify(serialize(service.history(actor(employee()), request.args)))


@reintegros_mobile_bp.post("/solicitudes")
@mobile_auth_required
def create():
    emp = employee()
    rid, created = service.store(emp, data(), request.files)
    return jsonify(
        solicitud=serialize(service.detail(actor(emp), rid)), repetido=not created
    ), (201 if created else 200)


@reintegros_mobile_bp.get("/solicitudes/<int:rid>")
@mobile_auth_required
def detail(rid):
    return jsonify(serialize(service.detail(actor(employee()), rid)))


@reintegros_mobile_bp.put("/solicitudes/<int:rid>")
@mobile_auth_required
def edit(rid):
    emp = employee()
    service.store(emp, data(), request.files, rid)
    return jsonify(serialize(service.detail(actor(emp), rid)))


@reintegros_mobile_bp.post("/solicitudes/<int:rid>/acciones")
@mobile_auth_required
def action(rid):
    who = actor(employee())
    service.transition(who, rid, data())
    return jsonify(serialize(service.detail(who, rid)))


@reintegros_mobile_bp.get("/fotos/<int:fid>")
@mobile_auth_required
def photo(fid):
    return private_photo(service.photo(actor(employee()), fid))


@reintegros_mobile_bp.get("/odometro/<int:fid>")
@mobile_auth_required
def odometer(fid):
    return private_photo(service.odometer_photo(actor(employee()), fid))


@reintegros_mobile_bp.get("/recordatorios")
@mobile_auth_required
def reminders():
    return jsonify(serialize(dict(items=service.monthly.reminders(employee()))))


@reintegros_mobile_bp.post("/recordatorios/<int:rid>/leido")
@mobile_auth_required
def read_reminder(rid):
    service.monthly.read_reminder(employee(), rid)
    return jsonify(ok=True)
