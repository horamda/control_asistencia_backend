import csv
import io
from uuid import uuid4
from flask import Blueprint, request, session, render_template, redirect, url_for, flash, Response, send_file
from services import seguridad_service as s
from services import seguridad_import_service as importer
from web.carga.carga_routes import scope, csv_safe
from routes.carga_routes import private_photo
from web.auth.decorators import permission_required

seguridad_web_bp=Blueprint('seguridad_web',__name__,url_prefix='/seguridad-higiene')


@seguridad_web_bp.before_request
def limits():
    request.max_content_length=27*1024*1024
    request.max_form_parts=150


@seguridad_web_bp.errorhandler(s.Error)
def invalid(exc): return render_template('seguridad/error.html',message=str(exc)),exc.status


def context(empresa):
    return dict(empresa_id=empresa,**s.config(empresa))


@seguridad_web_bp.get('/')
@permission_required('seguridad_higiene','ver')
def index():
    empresa,empresas=scope()
    result=s.history(empresa,request.args,page=max(1,request.args.get('page',1,type=int)))
    return render_template('seguridad/listado.html',**context(empresa),**result,empresas=empresas,filters=request.args)


@seguridad_web_bp.route('/nuevo',methods=['GET','POST'])
@permission_required('seguridad_higiene','crear')
@permission_required('seguridad_higiene','ver')
def create():
    empresa,_=scope()
    row_id=request.values.get('import_row',type=int)
    row=importer.pending(empresa,row_id) if row_id else None
    data=row['propuesta'] if row else dict(envio_id=str(uuid4()),involucrados=[],fecha_evento=s.now_local().date().isoformat())
    error=None
    if request.method=='POST':
        data=request.form.to_dict(); data['involucrados']=request.form.getlist('involucrados')
        if row: data['envio_id']=row['propuesta']['envio_id']
        try:
            eid,_=s.create(empresa,data,request.files.getlist('fotos'),user=session['user_id'],import_row=row_id)
            return redirect(url_for('seguridad_web.detail',event_id=eid,empresa_id=empresa))
        except s.Error as exc: error=str(exc)
    ctx=context(empresa)
    if row:
        with s.db.transaction() as c: ctx['empleados']=s.employees(c,empresa,False)
    return render_template('seguridad/form.html',**ctx,data=data,error=error,import_row=row,row=None)


@seguridad_web_bp.get('/eventos/<int:event_id>')
@permission_required('seguridad_higiene','ver')
def detail(event_id):
    empresa,_=scope()
    return render_template('seguridad/detalle.html',**context(empresa),row=s.detail(empresa,event_id))


@seguridad_web_bp.route('/eventos/<int:event_id>/editar',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','editar')
def edit(event_id):
    empresa,_=scope(); row=s.detail(empresa,event_id)
    data={**row,**row['detalles'],'involucrados':[p['empleado_id'] for p in row['involucrados']]}; error=None
    if request.method=='POST':
        data=request.form.to_dict(); data['involucrados']=request.form.getlist('involucrados')
        data['quitar_fotos']=request.form.getlist('quitar_fotos')
        try:
            s.edit(empresa,event_id,session['user_id'],data,request.files.getlist('fotos'))
            flash('Cambios guardados. El evento requiere nueva aprobación.','success')
            return redirect(url_for('seguridad_web.detail',event_id=event_id,empresa_id=empresa))
        except s.Error as exc: error=str(exc)
    ctx=context(empresa)
    if row['origen']=='importacion':
        with s.db.transaction() as c: ctx['empleados']=s.employees(c,empresa,False)
    return render_template('seguridad/form.html',**ctx,data=data,row=row,error=error,import_row=None)


@seguridad_web_bp.post('/eventos/<int:event_id>/revisar')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','aprobar')
def review(event_id):
    empresa,_=scope()
    if request.form.get('estado') not in ('aprobado','rechazado'):
        raise s.Error('Acción de revisión inválida.')
    s.review(empresa,event_id,session['user_id'],request.form.get('estado'),request.form.get('revision'),request.form.get('motivo'))
    return redirect(url_for('seguridad_web.detail',event_id=event_id,empresa_id=empresa))


@seguridad_web_bp.post('/eventos/<int:event_id>/anular')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','eliminar')
def annul(event_id):
    empresa,_=scope()
    s.review(empresa,event_id,session['user_id'],'anulado',request.form.get('revision'),request.form.get('motivo'))
    return redirect(url_for('seguridad_web.detail',event_id=event_id,empresa_id=empresa))


@seguridad_web_bp.get('/fotos/<int:photo_id>')
@permission_required('seguridad_higiene','ver')
def photo(photo_id):
    empresa,_=scope()
    return private_photo(s.photo(empresa,photo_id))


@seguridad_web_bp.route('/catalogos',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
def catalogs():
    empresa,_=scope()
    if request.method=='POST':
        from web.auth.decorators import can_access_module
        from flask import abort
        rid=request.form.get('id',type=int)
        if not can_access_module(session['user_id'],'seguridad_higiene','editar' if rid else 'crear'): abort(403)
        s.save_catalog(empresa,session['user_id'],request.form,rid)
        return redirect(url_for('seguridad_web.catalogs',empresa_id=empresa))
    return render_template('seguridad/catalogos.html',**context(empresa),clases=s.CLASES)


@seguridad_web_bp.post('/eventos/<int:event_id>/acciones')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','editar')
def action(event_id):
    empresa,_=scope()
    s.save_action(empresa,event_id,session['user_id'],request.form,request.form.get('id',type=int))
    return redirect(url_for('seguridad_web.detail',event_id=event_id,empresa_id=empresa))


@seguridad_web_bp.get('/ranking')
@permission_required('seguridad_higiene','ver')
def ranking():
    empresa,_=scope()
    result=s.rankings(empresa,request.args.get('anio',s.now_local().year),request.args.get('mes'),request.args)
    return render_template('seguridad/ranking.html',**context(empresa),**result,filters=request.args)


@seguridad_web_bp.get('/exportar')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','exportar')
def export():
    empresa,_=scope(); buffer=io.StringIO(); writer=csv.writer(buffer,delimiter=';')
    with s.db.transaction() as c:
        max_id=s.db.one(c,'SELECT COALESCE(MAX(id),0) id FROM sh_eventos WHERE empresa_id=%s',(empresa,))['id']
    writer.writerow(['id','fecha_evento','tipo','estado','categoria','descripcion','legajos','personas','sucursales','sectores','puestos'])
    page=1
    while True:
        result=s.history(empresa,request.args,page=page,max_id=max_id)
        for r in result['items']:
            with s.db.transaction() as c:
                people=s.db.all_rows(c,'SELECT * FROM sh_involucrados WHERE evento_id=%s ORDER BY nombre',(r['id'],))
            values=[r[k] for k in ('id','fecha_evento','tipo','estado','categoria_nombre','descripcion')]
            values += [' | '.join(str(p.get(k) or '') for p in people) for k in ('legajo','nombre','sucursal_nombre','sector_nombre','puesto_nombre')]
            writer.writerow([csv_safe(v) for v in values])
        if page*30>=result['total']: break
        page+=1
    return Response('\ufeff'+buffer.getvalue(),content_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=seguridad_higiene.csv'})


@seguridad_web_bp.route('/importar',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','crear')
def imports():
    empresa,_=scope()
    if request.method=='POST':
        bid=importer.stage(empresa,session['user_id'],request.files.get('archivo'))
        return redirect(url_for('seguridad_web.batch',batch_id=bid,empresa_id=empresa))
    with s.db.transaction() as c:
        rows=s.db.all_rows(c,'SELECT id,nombre,creado_at FROM sh_importaciones WHERE empresa_id=%s ORDER BY id DESC',(empresa,))
    return render_template('seguridad/importar.html',empresa_id=empresa,rows=rows,batch=None)


@seguridad_web_bp.route('/importar/<int:batch_id>',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','crear')
def batch(batch_id):
    empresa,_=scope(); page=max(1,request.args.get('page',1,type=int))
    if request.method=='POST':
        ok,unresolved=importer.import_ready(empresa,batch_id,session['user_id'])
        flash(f'{ok} eventos creados pendientes de aprobación; {unresolved} filas requieren resolución.','success')
        return redirect(url_for('seguridad_web.batch',batch_id=batch_id,empresa_id=empresa))
    return render_template('seguridad/importar.html',empresa_id=empresa,rows=[],batch=importer.batch(empresa,batch_id,page),page=page)


@seguridad_web_bp.get('/importar/<int:batch_id>/original')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','exportar')
def original(batch_id):
    empresa,_=scope()
    with s.db.transaction() as c:
        row=s.db.one(c,'SELECT archivo,nombre FROM sh_importaciones WHERE id=%s AND empresa_id=%s',(batch_id,empresa))
    if not row: raise s.Error('Importación no encontrada.',404)
    response=send_file(io.BytesIO(row['archivo']),download_name='respuestas_original.xlsx',as_attachment=True)
    response.headers['Cache-Control']='private, no-store'
    return response
