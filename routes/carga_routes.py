from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, g, jsonify, request, send_file
from mysql.connector import IntegrityError

from repositories import carga_repository as repo
from repositories.empleado_repository import get_by_id
from services import carga_service as service
from utils.jwt_guard import mobile_auth_required

carga_mobile_bp = Blueprint('carga_mobile', __name__, url_prefix='/api/v1/mobile/cargas')


def serialize(value):
    if isinstance(value, datetime):
        return value.isoformat() + '-03:00' if value.tzinfo is None else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    return value


def employee():
    row = get_by_id(int(g.mobile_empleado_id))
    if not row or not row.get('activo'):
        raise service.CargaError('Sesión no válida.', 401)
    return row


@carga_mobile_bp.errorhandler(service.CargaError)
def invalid(error):
    return jsonify(error=str(error)), error.status


@carga_mobile_bp.errorhandler(IntegrityError)
def conflict(error):
    return jsonify(error='El registro ya existe o entró en conflicto con otro envío. Actualice el historial.'), 409


@carga_mobile_bp.before_request
def limit_body():
    # Limite total antes de que Werkzeug lea multipart; limites individuales en el servicio.
    request.max_content_length = 27 * 1024 * 1024
    request.max_form_parts = 30


@carga_mobile_bp.errorhandler(413)
def too_large(error):
    return jsonify(error='El envío excede el límite. Máximo 5 fotos de 5 MB cada una.'), 413


@carga_mobile_bp.get('/config')
@mobile_auth_required
def configuration():
    return jsonify(serialize(service.config(employee())))


@carga_mobile_bp.post('')
@mobile_auth_required
def create():
    employee()  # Comprueba sesion; el servicio vuelve a leer identidad y puestos.
    data = request.get_json(silent=True) if request.is_json else request.form
    if not hasattr(data, 'get'):
        raise service.CargaError('Envíe un objeto JSON o un formulario multipart.')
    record_id, created = service.create(int(g.mobile_empleado_id), data, request.files.getlist('fotos'))
    emp = employee()
    row = repo.detail(record_id, emp['empresa_id'], emp['id'])
    return jsonify(registro=serialize(row), repetido=not created), 201 if created else 200


@carga_mobile_bp.get('')
@mobile_auth_required
def history():
    emp = employee()
    page = max(1, request.args.get('page', 1, type=int))
    rows, total = repo.history(emp['empresa_id'], {}, empleado_id=emp['id'], page=page)
    return jsonify(items=serialize(rows), total=total, page=page, per_page=30)


@carga_mobile_bp.get('/<int:record_id>')
@mobile_auth_required
def detail(record_id):
    emp = employee()
    row = repo.detail(record_id, emp['empresa_id'], emp['id'])
    if not row:
        raise service.CargaError('Registro no encontrado.', 404)
    return jsonify(serialize(row))


@carga_mobile_bp.get('/fotos/<int:photo_id>')
@mobile_auth_required
def photo(photo_id):
    emp = employee()
    row = repo.photo(photo_id, emp['empresa_id'], emp['id'])
    if not row:
        raise service.CargaError('Foto no encontrada.', 404)
    return private_photo(row)


def private_photo(row):
    response = send_file(BytesIO(row['contenido']), mimetype='image/jpeg', max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
