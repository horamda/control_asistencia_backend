from __future__ import annotations

import datetime as dt
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from repositories import skap_matriz_repository as repo
from services.skap_excel_service import MAX_BYTES, match_employees, normalize, parse_workbook
from web.auth.decorators import _cached_web_user, login_required

skap_matriz_bp = Blueprint('skap_matriz', __name__, url_prefix='/skap')


def current_actor():
    user = _cached_web_user(session.get('user_id'))
    if not user or not user.get('activo') or not user.get('empresa_id'):
        abort(403)
    return {**user, 'rol': str(user.get('rol') or '').lower()}


def manager(actor):
    return actor['rol'] in {'admin', 'rrhh', 'supervisor'}


def importer():
    actor = current_actor()
    if actor['rol'] not in {'admin', 'rrhh'}:
        abort(403)
    return actor


@skap_matriz_bp.get('/mis-evaluaciones')
@login_required
def mine():
    actor = current_actor()
    if not actor.get('empleado_id'):
        abort(403, description='Tu usuario no tiene un legajo vinculado.')
    rows = repo.list_evaluations(actor, own=True)
    return render_template('skap/matrices.html', rows=rows, own=True, actor=actor, branches=[], filters={})


@skap_matriz_bp.get('/matrices')
@login_required
def index():
    actor = current_actor()
    if not manager(actor):
        return redirect(url_for('skap_matriz.mine'))
    filters = {key: request.args.get(key, type=int) for key in ('anio','sucursal_id','empleado_id')}
    rows = repo.list_evaluations(actor, **filters)
    roles = sorted({row['rol_clave']: row['rol'] for row in rows}.items())
    filters['rol'] = normalize(request.args.get('rol'))
    if filters['rol']:
        rows = [row for row in rows if row['rol_clave'] == filters['rol']]
    return render_template('skap/matrices.html',rows=rows,own=False,actor=actor,
                           branches=repo.branch_options(actor['empresa_id']),filters=filters,roles=roles)


@skap_matriz_bp.get('/matrices/<int:evaluation_id>')
@login_required
def detail(evaluation_id):
    actor = current_actor()
    ev = repo.get_evaluation(evaluation_id, actor)
    if not ev:
        abort(404)
    editable = manager(actor) and ev['empleado_id'] != actor.get('empleado_id')
    staff = repo.employee_options(actor['empresa_id']) if editable else []
    return render_template('skap/matriz_detalle.html',ev=ev,editable=editable,staff=staff)


@skap_matriz_bp.route('/matrices/importar', methods=['GET','POST'])
@login_required
def upload():
    actor = importer()
    error = None
    if request.method == 'POST':
        file = request.files.get('archivo')
        try:
            if not file or not str(file.filename).lower().endswith('.xlsx'):
                raise ValueError('Seleccione un archivo .xlsx.')
            payload = parse_workbook(file.read(MAX_BYTES + 1), file.filename)
            match_employees(payload,repo.employee_options(actor['empresa_id']),repo.branch_options(actor['empresa_id']),aliases=repo.name_aliases(actor['empresa_id']))
            import_id = repo.save_preview(payload,actor['empresa_id'],actor['id'])
            return redirect(url_for('skap_matriz.preview',import_id=import_id))
        except ValueError as exc:
            error = str(exc)
    return render_template('skap/matriz_importar.html',error=error,batches=repo.list_imports(actor['empresa_id']))


@skap_matriz_bp.route('/matrices/importaciones/<int:import_id>',methods=['GET','POST'])
@login_required
def preview(import_id):
    actor = importer()
    batch = repo.get_import(import_id,actor['empresa_id'])
    if not batch:
        abort(404)
    staff = repo.employee_options(actor['empresa_id'])
    payload = batch['payload']
    error = None
    if request.method == 'POST':
        try:
            overrides = {ev['clave']: request.form.get('empleado_'+ev['clave']) for ev in payload['evaluaciones']}
            match_employees(payload,staff,repo.branch_options(actor['empresa_id']),overrides,repo.name_aliases(actor['empresa_id']))
            selected = set(request.form.getlist('seleccion'))
            if not selected.issubset({e['clave'] for e in payload['evaluaciones']}):
                raise ValueError('Selección inválida.')
            if request.form.get('operacion') == 'importar':
                result = repo.commit_import(import_id,payload,actor,selected)
                flash(f"Se incorporaron {len(result['creadas'])} evaluaciones; {len(result['duplicadas_omitidas'])} duplicadas omitidas.",'success')
                return redirect(url_for('skap_matriz.index'))
        except (ValueError,TypeError) as exc:
            error = str(exc)
    return render_template('skap/matriz_previa.html',batch=batch,payload=payload,staff=staff,error=error)


@skap_matriz_bp.post('/matrices/importaciones/<int:import_id>/revertir')
@login_required
def revert(import_id):
    actor = importer()
    try:
        count = repo.revert_import(import_id,actor)
        flash(f'Importación revertida: {count} evaluaciones retiradas.','success')
    except ValueError as exc:
        flash(str(exc),'error')
    return redirect(url_for('skap_matriz.upload'))


def action_data(form, staff):
    data = {k: (form.get(k) or '').strip() for k in ('accion','estado','comentarios')}
    if not data['accion'] or len(data['accion']) > 5000:
        raise ValueError('La acción debe contener entre 1 y 5000 caracteres.')
    if data['estado'] not in {'propuesta','pendiente','en_proceso','completado','cancelado'}:
        raise ValueError('Estado inválido.')
    data['progreso'] = int(form.get('progreso') or 0)
    if not 0 <= data['progreso'] <= 100:
        raise ValueError('El progreso debe estar entre 0 y 100.')
    if data['estado'] == 'completado':
        data['progreso'] = 100
    elif data['progreso'] == 100 and data['estado'] != 'cancelado':
        raise ValueError('Un progreso de 100 requiere el estado completado.')
    data['responsable_empleado_id'] = int(form.get('responsable_empleado_id') or 0) or None
    if data['responsable_empleado_id'] and data['responsable_empleado_id'] not in {e['id'] for e in staff if e['activo']}:
        raise ValueError('Responsable no válido para esta empresa.')
    for key in ('fecha_inicio','fecha_fin'):
        data[key] = dt.date.fromisoformat(form[key]) if form.get(key) else None
    if data['fecha_inicio'] and data['fecha_fin'] and data['fecha_fin'] < data['fecha_inicio']:
        raise ValueError('La fecha de fin debe ser posterior o igual a la de inicio.')
    return data


@skap_matriz_bp.post('/matrices/<int:evaluation_id>/acciones/<int:action_id>')
@login_required
def edit_action(evaluation_id, action_id):
    actor = current_actor()
    ev = repo.get_evaluation(evaluation_id,actor)
    if not ev:
        abort(404)
    if not manager(actor) or actor.get('empleado_id') == ev['empleado_id']:
        abort(403)
    try:
        data = action_data(request.form,repo.employee_options(actor['empresa_id']))
        repo.update_action(ev,action_id,data,actor)
        flash('Acción actualizada.','success')
    except ValueError as exc:
        flash(str(exc),'error')
    return redirect(url_for('skap_matriz.detail',evaluation_id=evaluation_id))
