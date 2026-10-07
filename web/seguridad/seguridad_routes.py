import csv
import io
from uuid import uuid4
from flask import Blueprint, request, session, render_template, redirect, url_for, flash, Response, send_file
from services import seguridad_service as s
from services import seguridad_import_service as importer
from services import seguridad_excel_service as excel
from services import seguridad_dashboard_service as dashboard_service
from services import seguridad_campeon_service as champion
from web.carga.carga_routes import scope, csv_safe
from routes.carga_routes import private_photo
from web.auth.decorators import permission_required

seguridad_web_bp=Blueprint('seguridad_web',__name__,url_prefix='/seguridad-higiene')


@seguridad_web_bp.get('/campeon')
@permission_required('seguridad_higiene','ver')
def safety_champion():
    empresa,empresas=scope()
    result=champion.build(empresa,request.args.get('anio',s.now_local().year),request.args.get('mes'))
    return render_template('seguridad/campeon.html',empresa_id=empresa,empresas=empresas,agrupaciones=champion.GROUPS,**result)


@seguridad_web_bp.post('/campeon/reglas')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','editar')
def champion_rules():
    empresa,_=scope()
    champion.save_rules(empresa,session['user_id'],request.form)
    flash('Reglas actualizadas. Los reconocimientos confirmados conservan sus reglas originales.','success')
    return redirect(url_for('seguridad_web.safety_champion',empresa_id=empresa))


@seguridad_web_bp.post('/campeon/confirmar')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','aprobar')
def champion_confirm():
    empresa,_=scope()
    champion.confirm(empresa,session['user_id'],request.form)
    flash('Reconocimiento confirmado y guardado con sus reglas y ganadores.','success')
    return redirect(url_for('seguridad_web.safety_champion',empresa_id=empresa,anio=request.form['anio'],mes=request.form.get('mes',0)))


@seguridad_web_bp.before_request
def limits():
    request.max_content_length=27*1024*1024
    request.max_form_parts=150


@seguridad_web_bp.errorhandler(s.Error)
def invalid(exc): return render_template('seguridad/error.html',message=str(exc)),exc.status


def context(empresa,historical=False,**options):
    return dict(empresa_id=empresa,**s.config(empresa,historical=historical,inactive_externals=True,**options))


def form_data():
    data=request.form.to_dict()
    data['involucrados']=request.form.getlist('involucrados')
    data['externos']=[dict(id=value) for value in request.form.getlist('externos_id')]
    names=request.form.getlist('externo_nombre')
    companies=request.form.getlist('externo_empresa')
    data['externos'] += [dict(nombre=name,empresa=companies[i] if i<len(companies) else '') for i,name in enumerate(names)]
    return data


@seguridad_web_bp.get('/')
@permission_required('seguridad_higiene','ver')
def index():
    empresa,empresas=scope()
    result=s.history(empresa,request.args,page=max(1,request.args.get('page',1,type=int)))
    ctx=context(empresa,historical=True)
    with s.db.transaction() as c:
        ids=[r['id'] for r in result['items']]
        participants={i:[] for i in ids}
        if ids:
            marks=','.join(['%s']*len(ids))
            for p in s.db.all_rows(c,f'SELECT evento_id,nombre,legajo FROM {s.CURRENT_PARTICIPANTS} current_people WHERE evento_id IN ({marks})',tuple(ids)):
                participants[p['evento_id']].append(dict(nombre=p['nombre'],referencia='Legajo '+p['legajo']))
            for p in s.db.all_rows(c,f'SELECT evento_id,nombre,empresa FROM sh_evento_externos WHERE evento_id IN ({marks})',tuple(ids)):
                participants[p['evento_id']].append(dict(nombre=p['nombre'],referencia=p['empresa'] or 'Externo'))
        for r in result['items']: r['personas']=participants[r['id']]
    return render_template('seguridad/listado.html',**ctx,**result,empresas=empresas,filters=dict(request.args,empresa_id=empresa))


@seguridad_web_bp.get('/dashboard')
@permission_required('seguridad_higiene','ver')
def dashboard():
    empresa,empresas=scope()
    result=dashboard_service.build(empresa,request.args)
    filters={k:request.args[k] for k in ('sucursal_id','sector_id','puesto_id') if request.args.get(k)}
    filters.update(empresa_id=empresa,desde=result['desde'].isoformat(),hasta=result['hasta'].isoformat(),vista=result['vista'])
    record_filters={k:v for k,v in filters.items() if k!='vista'}
    record_filters['estado']='aprobado'
    if result['vista'] in ('seguro','inseguro'): record_filters['tipo']=result['vista']
    return render_template('seguridad/dashboard.html',**result,empresa_id=empresa,empresas=empresas,filters=filters,record_filters=record_filters,tipos=s.TIPOS)


@seguridad_web_bp.post('/dashboard/configuracion')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','editar')
def dashboard_configuration():
    empresa,_=scope()
    dashboard_service.save_configuration(empresa,session['user_id'],request.form.get('inicio'))
    flash('Inicio del registro confiable actualizado.','success')
    return redirect(url_for('seguridad_web.dashboard',empresa_id=empresa,vista='indicadores'))


@seguridad_web_bp.route('/nuevo',methods=['GET','POST'])
@permission_required('seguridad_higiene','crear')
@permission_required('seguridad_higiene','ver')
def create():
    empresa,_=scope()
    row_id=request.values.get('import_row',type=int)
    row=importer.pending(empresa,row_id) if row_id else None
    data=row['propuesta'] if row else dict(envio_id=str(uuid4()),involucrados=[],fecha_evento=s.now_local().date().isoformat(),tipo=request.args.get('tipo') if request.args.get('tipo') in s.TIPOS else '')
    error=None
    if request.method=='POST':
        data=form_data()
        if row: data['envio_id']=row['propuesta']['envio_id']
        try:
            eid,_=s.create(empresa,data,request.files.getlist('fotos'),user=session['user_id'],import_row=row_id)
            return redirect(url_for('seguridad_web.detail',event_id=eid,empresa_id=empresa))
        except s.Error as exc: error=str(exc)
    ctx=context(empresa,historical=bool(row))
    return render_template('seguridad/form.html',**ctx,data=data,error=error,import_row=row,row=None)


@seguridad_web_bp.get('/eventos/<int:event_id>')
@permission_required('seguridad_higiene','ver')
def detail(event_id):
    empresa,_=scope()
    return render_template('seguridad/detalle.html',**context(empresa,include_catalogs=False,include_externals=False),row=s.detail(empresa,event_id))


@seguridad_web_bp.route('/eventos/<int:event_id>/editar',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','editar')
def edit(event_id):
    empresa,_=scope(); row=s.detail(empresa,event_id)
    data={**row,**row['detalles'],'involucrados':[p['empleado_id'] for p in row['involucrados']]}; error=None
    if request.method=='POST':
        data=form_data()
        data['quitar_fotos']=request.form.getlist('quitar_fotos')
        try:
            s.edit(empresa,event_id,session['user_id'],data,request.files.getlist('fotos'))
            flash('Cambios guardados. El evento requiere nueva aprobación.','success')
            return redirect(url_for('seguridad_web.detail',event_id=event_id,empresa_id=empresa))
        except s.Error as exc: error=str(exc)
    ctx=context(empresa,historical=row['origen']=='importacion')
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
    ctx=context(empresa,include_employees=False,include_externals=False)
    query=request.args.get('q','').strip()[:180]
    kind=request.args.get('tipo','');state=request.args.get('estado','')
    if kind and kind not in s.TIPOS or state not in ('','0','1'): raise s.Error('Filtro inválido.')
    ctx['catalogos']=[r for r in ctx['catalogos'] if (not query or query.casefold() in r['nombre'].casefold())
        and (not kind or r['tipo']==kind) and (not state or str(r['activo'])==state)]
    return render_template('seguridad/catalogos.html',**ctx,clases=s.CLASES,query=query,kind=kind,state=state)


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
    return render_template('seguridad/ranking.html',**context(empresa,include_catalogs=False,include_externals=False),**result,filters=request.args)


@seguridad_web_bp.get('/exportar')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','exportar')
def export():
    empresa,_=scope(); buffer=io.StringIO(); writer=csv.writer(buffer,delimiter=';')
    with s.db.transaction() as c:
        max_id=s.db.one(c,'SELECT COALESCE(MAX(id),0) id FROM sh_eventos WHERE empresa_id=%s',(empresa,))['id']
    writer.writerow(['id','fecha_evento','tipo','estado','categoria','descripcion','legajos','personas','sucursales','sectores','puestos','ids_externos','nombres_externos','empresas_externas'])
    page=1
    while True:
        result=s.history(empresa,request.args,page=page,max_id=max_id)
        ids=[r['id'] for r in result['items']]
        people_by_event={i:[] for i in ids};externals_by_event={i:[] for i in ids}
        if ids:
            marks=','.join(['%s']*len(ids))
            with s.db.transaction() as c:
                for person in s.db.all_rows(c,f'SELECT * FROM {s.CURRENT_PARTICIPANTS} current_people WHERE evento_id IN ({marks}) ORDER BY nombre',tuple(ids)):
                    people_by_event[person['evento_id']].append(person)
                for person in s.db.all_rows(c,f'SELECT evento_id,externo_id,nombre,empresa FROM sh_evento_externos WHERE evento_id IN ({marks}) ORDER BY nombre,externo_id',tuple(ids)):
                    externals_by_event[person['evento_id']].append(person)
        for r in result['items']:
            people=people_by_event[r['id']]
            externals=externals_by_event[r['id']]
            values=[r[k] for k in ('id','fecha_evento','tipo','estado','categoria_nombre','descripcion')]
            values += [' | '.join(str(p.get(k) or '') for p in people) for k in ('legajo','nombre','sucursal_nombre','sector_nombre','puesto_nombre')]
            values += [' | '.join(str(p.get(k) or '') for p in externals) for k in ('externo_id','nombre','empresa')]
            writer.writerow([csv_safe(v) for v in values])
        if page*30>=result['total']: break
        page+=1
    return Response('\ufeff'+buffer.getvalue(),content_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=seguridad_higiene.csv'})


@seguridad_web_bp.route('/importar',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','crear')
def imports():
    empresa,_=scope()
    validation_errors=[]
    if request.method=='POST':
        try:
            bid=importer.stage(empresa,session['user_id'],request.files.get('archivo'))
            return redirect(url_for('seguridad_web.batch',batch_id=bid,empresa_id=empresa))
        except importer.ValidationError as exc:
            validation_errors=exc.issues
    with s.db.transaction() as c:
        rows=s.db.all_rows(c,'SELECT id,nombre,creado_at FROM sh_importaciones WHERE empresa_id=%s ORDER BY id DESC',(empresa,))
    return render_template('seguridad/importar.html',empresa_id=empresa,rows=rows,batch=None,
                           validation_errors=validation_errors),400 if validation_errors else 200


@seguridad_web_bp.get('/importar/plantilla')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','crear')
def import_template():
    empresa,_=scope()
    response=send_file(io.BytesIO(excel.export(empresa)),download_name='seguridad_higiene_plantilla.xlsx',as_attachment=True)
    response.headers['Cache-Control']='private, no-store'
    return response


@seguridad_web_bp.get('/importar/<int:batch_id>/corregir')
@permission_required('seguridad_higiene','ver')
@permission_required('seguridad_higiene','crear')
@permission_required('seguridad_higiene','exportar')
def import_correctable(batch_id):
    empresa,_=scope()
    response=send_file(io.BytesIO(excel.export(empresa,batch_id)),download_name=f'seguridad_higiene_lote_{batch_id}_corregir.xlsx',as_attachment=True)
    response.headers['Cache-Control']='private, no-store'
    return response


@seguridad_web_bp.route('/externos',methods=['GET','POST'])
@permission_required('seguridad_higiene','ver')
def external_people():
    empresa,_=scope()
    error=None
    draft=None
    if request.method=='POST':
        from web.auth.decorators import can_access_module
        record_id=request.form.get('id',type=int)
        if not can_access_module(session['user_id'],'seguridad_higiene','editar' if record_id else 'crear'):
            raise s.Error('No tiene permiso para modificar personas externas.',403)
        try:
            s.save_external(empresa,session['user_id'],request.form,record_id)
            flash('Persona externa actualizada.' if record_id else 'Persona externa creada.','success')
            return redirect(url_for('seguridad_web.external_people',empresa_id=empresa,q=request.args.get('q',''),estado=request.args.get('estado',''),page=request.args.get('page',1,type=int)))
        except s.Error as exc:
            if exc.status!=400: raise
            error=str(exc);draft=request.form.to_dict()
    query=request.args.get('q','').strip()[:180]
    state=request.args.get('estado','')
    if state not in ('','1','0'): raise s.Error('Estado inválido.')
    page=max(1,request.args.get('page',1,type=int))
    with s.db.transaction() as c:
        people=s.external_people(c,empresa,False)
        counts={r['externo_id']:r for r in s.db.all_rows(c,'''SELECT x.externo_id,COUNT(*) total,MAX(e.fecha_evento) ultima_fecha
            FROM sh_evento_externos x JOIN sh_eventos e ON e.id=x.evento_id WHERE e.empresa_id=%s GROUP BY x.externo_id''',(empresa,))}
    summary=dict(total=len(people),activos=sum(bool(p['activo']) for p in people))
    people=[p for p in people if (not state or str(p['activo'])==state) and (not query or query.casefold() in (p['nombre']+' '+p['empresa']).casefold())]
    total=len(people);page=min(page,max(1,(total+29)//30))
    for p in people: p.update(counts.get(p['id'],dict(total=0,ultima_fecha=None)))
    return render_template('seguridad/externos.html',empresa_id=empresa,people=people[(page-1)*30:page*30],
        total=total,page=page,summary=summary,query=query,state=state,error=error,draft=draft)


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
