import csv
import io
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, Response, stream_with_context
from repositories import carga_repository as repo
from repositories.empresa_repository import get_all as get_empresas
from repositories.usuarios_app_repository import get_by_id as get_user
from services import carga_service as service
from routes.carga_routes import private_photo
from web.auth.decorators import permission_required, can_access_module

carga_web_bp = Blueprint('carga_web', __name__, url_prefix='/validacion-carga')


def scope():
    user = get_user(session['user_id'])
    if not user or not user.get('activo'):
        abort(403)
    empresas = get_empresas(include_inactive=True) if user['rol'] == 'admin' else []
    empresa_id = int(user['empresa_id'])
    if user['rol'] == 'admin' and request.values.get('empresa_id'):
        empresa_id = service.positive_int(request.values.get('empresa_id'), 'Empresa')
        if empresa_id not in {e['id'] for e in empresas}:
            abort(404)
    return empresa_id, empresas


def filters():
    result = {k: request.args.get(k, '') for k in ('desde', 'hasta', 'q', 'camion_id', 'sucursal_empleado_id', 'tipo', 'valida', 'en_horario')}
    for key in ('desde', 'hasta'):
        if result[key]:
            service.date_field(result[key])
    if result['desde'] and result['hasta'] and result['hasta'] < result['desde']:
        raise service.CargaError('La fecha Hasta debe ser igual o posterior a Desde.')
    for key in ('camion_id', 'sucursal_empleado_id'):
        if result[key]:
            service.positive_int(result[key], key)
    if result['tipo'] not in ('', 'inicial', 'recarga') or any(result[k] not in ('', '0', '1') for k in ('valida', 'en_horario')):
        raise service.CargaError('Filtro inválido.')
    return result


@carga_web_bp.errorhandler(service.CargaError)
def invalid(error):
    return render_template('carga/error.html', message=str(error)), error.status


@carga_web_bp.get('/')
@permission_required('validacion_carga', 'ver')
def index():
    empresa_id, empresas = scope()
    page = max(1, request.args.get('page', 1, type=int))
    search = filters()
    rows, total = repo.history(empresa_id, search, page=page)
    catalogs = repo.catalogs(empresa_id)
    return render_template('carga/listado.html', rows=rows, total=total, page=page, empresa_id=empresa_id,
        empresas=empresas, filters=search, **catalogs)


@carga_web_bp.get('/<int:record_id>')
@permission_required('validacion_carga', 'ver')
def detail(record_id):
    empresa_id, _ = scope()
    row = repo.detail(record_id, empresa_id)
    if not row:
        abort(404)
    return render_template('carga/detalle.html', row=row, empresa_id=empresa_id, clock=service.format_minutes)


@carga_web_bp.get('/fotos/<int:photo_id>')
@permission_required('validacion_carga', 'ver')
def photo(photo_id):
    empresa_id, _ = scope()
    row = repo.photo(photo_id, empresa_id)
    if not row:
        abort(404)
    return private_photo(row)


@carga_web_bp.get('/catalogos')
@permission_required('validacion_carga', 'ver')
def catalogs():
    empresa_id, empresas = scope()
    return render_template('carga/catalogos.html', empresa_id=empresa_id, empresas=empresas,
        clock=service.format_minutes, **repo.catalogs(empresa_id))


@carga_web_bp.route('/catalogos/<kind>/nuevo', methods=['GET', 'POST'])
@carga_web_bp.route('/catalogos/<kind>/<int:record_id>/editar', methods=['GET', 'POST'])
@permission_required('validacion_carga', 'ver')
def edit_catalog(kind, record_id=None):
    if kind not in ('camiones', 'horarios'):
        abort(404)
    empresa_id, _ = scope()
    action = 'editar' if record_id else 'crear'
    if not can_access_module(session['user_id'], 'validacion_carga', action):
        abort(403)
    catalog = repo.catalogs(empresa_id)
    data = next((r for r in catalog[kind] if r['id'] == record_id), None) if record_id else {'activo': 1}
    if record_id and not data:
        abort(404)
    if kind == 'horarios':
        data = {**data, 'desde': service.format_minutes(data.get('desde_minuto', 0)),
            'hasta': service.format_minutes(data.get('hasta_minuto', 485)),
            'vigente_desde': data.get('vigente_desde', service.now_local().date())}
    error = None
    if request.method == 'POST':
        data = request.form.to_dict()
        try:
            service.save_catalog(kind, record_id, empresa_id, session['user_id'], data)
            flash('Configuración guardada.', 'success')
            return redirect(url_for('carga_web.catalogs', empresa_id=empresa_id))
        except service.CargaError as exc:
            error = str(exc)
    return render_template('carga/form.html', kind=kind, record_id=record_id, data=data, error=error,
        empresa_id=empresa_id, sucursales=catalog['sucursales'])


@carga_web_bp.post('/puestos')
@permission_required('validacion_carga', 'editar')
def positions():
    empresa_id, _ = scope()
    service.save_positions(empresa_id, session['user_id'], request.form.getlist('puesto_ids'))
    flash('Puestos habilitados actualizados.', 'success')
    return redirect(url_for('carga_web.catalogs', empresa_id=empresa_id))


@carga_web_bp.get('/auditoria')
@permission_required('validacion_carga', 'ver')
def audit():
    empresa_id, _ = scope()
    page = max(1, request.args.get('page', 1, type=int))
    with repo.transaction() as c:
        rows = repo.all_rows(c, 'SELECT * FROM carga_auditoria WHERE empresa_id=%s ORDER BY id DESC LIMIT 50 OFFSET %s', (empresa_id, (page - 1) * 50))
    return render_template('carga/auditoria.html', rows=rows, page=page, empresa_id=empresa_id)


def csv_safe(value):
    text = '' if value is None else str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


@carga_web_bp.get('/exportar')
@permission_required('validacion_carga', 'exportar')
def export():
    empresa_id, _ = scope()
    search = filters()
    with repo.transaction() as c:
        max_id = repo.one(c, 'SELECT COALESCE(MAX(id),0) id FROM carga_validaciones WHERE empresa_id=%s', (empresa_id,))['id']
    columns = ['id', 'registrado_at', 'legajo', 'empleado_nombre', 'sucursal_empleado_nombre', 'camion_numero',
        'camion_patente', 'sucursal_camion_nombre', 'tipo', 'consolidado', 'valida', 'en_horario', 'observaciones', 'fotos_cantidad']
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';')
        yield '\ufeff'
        writer.writerow(columns)
        yield buffer.getvalue()
        page = 1
        while True:
            rows, total = repo.history(empresa_id, search, page=page, per_page=500, max_id=max_id)
            buffer.seek(0)
            buffer.truncate(0)
            for row in rows:
                writer.writerow([csv_safe(row.get(k)) for k in columns])
            yield buffer.getvalue()
            if page * 500 >= total:
                break
            page += 1
    return Response(stream_with_context(generate()), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=validaciones_carga.csv'})
