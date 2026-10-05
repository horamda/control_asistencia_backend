from flask import Blueprint, jsonify, request
from utils.jwt_guard import mobile_auth_required
from routes.carga_routes import employee, serialize, private_photo
from services import seguridad_service as s

seguridad_mobile_bp=Blueprint('seguridad_mobile',__name__,url_prefix='/api/v1/mobile/seguridad')


@seguridad_mobile_bp.before_request
def limits():
    request.max_content_length=27*1024*1024
    request.max_form_parts=40


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
    return jsonify(serialize(s.history(emp['empresa_id'],request.args,emp['id'],mode,max(1,request.args.get('page',1,type=int)))))


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
    result=s.rankings(emp['empresa_id'],request.args.get('anio',s.now_local().year),request.args.get('mes'))
    # El ranking compartido no expone accidentes ni datos de lesiones de compañeros.
    result['rankings']={k:v for k,v in result['rankings'].items() if k in ('seguro','inseguro')}
    result['eventos']=[r for r in result['eventos'] if r['tipo'] in ('seguro','inseguro')]
    return jsonify(result)
