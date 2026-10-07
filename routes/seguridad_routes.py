from flask import Blueprint, jsonify, request
from utils.jwt_guard import mobile_auth_required
from routes.carga_routes import employee, serialize, private_photo
from services import seguridad_service as s
from services import seguridad_mobile_dashboard_service as dashboard

seguridad_mobile_bp=Blueprint('seguridad_mobile',__name__,url_prefix='/api/v1/mobile/seguridad')


@seguridad_mobile_bp.before_request
def limits():
    request.max_content_length=27*1024*1024
    request.max_form_parts=40


@seguridad_mobile_bp.after_request
def private_response(response):
    response.headers['Cache-Control']='private, no-store'
    return response


@seguridad_mobile_bp.errorhandler(s.Error)
def invalid(exc): return jsonify(error=str(exc)),exc.status


@seguridad_mobile_bp.errorhandler(413)
def large(exc): return jsonify(error='Máximo 5 fotos de 5 MB cada una.'),413


@seguridad_mobile_bp.get('/config')
@mobile_auth_required
def config():
    emp=employee()
    result=s.config(emp['empresa_id'],emp)
    result['catalogos']=[c for c in result['catalogos'] if c['activo']]
    result['dashboard']=dict(version_contrato='1.33.2',historial_propio=True,indicadores=True,
        ranking_alcances=['empresa','sucursal'] if emp.get('sucursal_id') else ['empresa'],sucursal_id=emp.get('sucursal_id'))
    return jsonify(serialize(result))


@seguridad_mobile_bp.route('/eventos',methods=['GET','POST'])
@mobile_auth_required
def events():
    emp=employee()
    if request.method=='POST':
        data=request.get_json(silent=True) if request.is_json else request.form
        if not hasattr(data,'get'): raise s.Error('Envíe un objeto JSON o formulario multipart.')
        event_id,created=s.create(emp['empresa_id'],data,request.files.getlist('fotos'),reporter=emp)
        state=s.detail(emp['empresa_id'],event_id,emp['id'])['estado']
        return jsonify(id=event_id,estado=state,repetido=not created),201 if created else 200
    mode=request.args.get('vista','propio')
    if mode not in ('propio','enviados'): raise s.Error('Vista inválida.')
    filters={key:request.args[key] for key in ('tipo','estado','desde','hasta') if request.args.get(key)}
    return jsonify(serialize(s.history(emp['empresa_id'],filters,emp['id'],mode,max(1,request.args.get('page',1,type=int)))))


@seguridad_mobile_bp.get('/resumen')
@mobile_auth_required
def summary():
    return jsonify(serialize(dashboard.summary(employee(),request.args.get('anio'),request.args.get('mes'))))


@seguridad_mobile_bp.get('/indicadores')
@mobile_auth_required
def indicators():
    return jsonify(serialize(dashboard.indicators(employee(),request.args.get('hasta'))))


@seguridad_mobile_bp.get('/eventos/<int:event_id>')
@mobile_auth_required
def detail(event_id):
    emp=employee()
    return jsonify(serialize(s.detail(emp['empresa_id'],event_id,emp['id'])))


@seguridad_mobile_bp.get('/fotos/<int:photo_id>')
@mobile_auth_required
def photo(photo_id):
    emp=employee()
    return private_photo(s.photo(emp['empresa_id'],photo_id,emp['id']))


@seguridad_mobile_bp.get('/ranking')
@mobile_auth_required
def ranking():
    emp=employee()
    scope=request.args.get('alcance','empresa')
    if scope not in ('empresa','sucursal'): raise s.Error('Alcance inválido.')
    if scope=='sucursal' and not emp.get('sucursal_id'): raise s.Error('El empleado no tiene sucursal asignada.')
    result=s.rankings(emp['empresa_id'],request.args.get('anio',s.now_local().year),request.args.get('mes'),
        {'sucursal_id':emp['sucursal_id']} if scope=='sucursal' else None)
    # El ranking compartido no expone accidentes ni datos de lesiones de compañeros.
    result['rankings']={k:v for k,v in result['rankings'].items() if k in ('seguro','inseguro')}
    result['rankings_externos']={k:v for k,v in result['rankings_externos'].items() if k in ('seguro','inseguro')}
    result['eventos']=[r for r in result['eventos'] if r['tipo'] in ('seguro','inseguro')]
    result['alcance']=scope
    result['sucursal_id']=emp.get('sucursal_id') if scope=='sucursal' else None
    result['mi_posicion']={kind:next((row for row in rows if row['empleado_id']==emp['id']),None) for kind,rows in result['rankings'].items()}
    return jsonify(result)
