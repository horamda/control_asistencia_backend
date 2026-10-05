"""Seguridad e Higiene: identidad, revisión, privacidad y estadísticas."""
import hashlib
import json
import re
from datetime import date
from uuid import UUID
from repositories import carga_repository as db
from services.carga_service import CargaError, now_local, prepare_photos, positive_int, text_field, date_field

Error = CargaError
TIPOS = {'seguro': 'Comportamiento seguro', 'inseguro': 'Comportamiento inseguro',
         'incidente': 'Incidente sin lesión', 'accidente': 'Accidente'}
CLASES = ('categoria', 'lugar', 'clasificacion', 'atencion', 'lesion', 'parte_cuerpo')
DETALLES = ('advertido', 'lugar', 'clasificacion', 'atencion', 'lesion', 'parte_cuerpo')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def audit(c, empresa, user, accion, datos, evento=None):
    db.insert(c, 'sh_auditoria', dict(empresa_id=empresa, usuario_id=user, accion=accion,
        datos=dumps(datos), evento_id=evento, creado_at=now_local()))


def employees(c, empresa, active=True):
    return db.all_rows(c, '''SELECT e.id,e.activo,e.legajo,e.nombre,e.apellido,e.sucursal_id,e.sector_id,e.puesto_id,
        s.nombre sucursal_nombre,sec.nombre sector_nombre,p.nombre puesto_nombre
        FROM empleados e LEFT JOIN sucursales s ON s.id=e.sucursal_id
        LEFT JOIN sectores sec ON sec.id=e.sector_id LEFT JOIN puestos p ON p.id=e.puesto_id
        WHERE e.empresa_id=%s ''' + ('AND e.activo=1 ' if active else '') + 'ORDER BY e.apellido,e.nombre', (empresa,))


def config(empresa, employee=None):
    with db.transaction() as c:
        people = employees(c, empresa)
        if employee:
            people = [p for p in people if p['id'] == employee['id'] or
                (employee.get('sucursal_id') is not None and p['sucursal_id'] == employee['sucursal_id'])]
        cats = db.all_rows(c, 'SELECT * FROM sh_catalogos WHERE empresa_id=%s ORDER BY clase,tipo,nombre', (empresa,))
    return dict(tipos=TIPOS, empleados=people, catalogos=cats, max_fotos=5, max_foto_bytes=5*1024*1024,
                fecha_actual=now_local().date().isoformat())


def parse(data):
    tipo = data.get('tipo')
    if tipo not in TIPOS:
        raise Error('Seleccione un tipo válido.')
    fecha = date_field(data.get('fecha_evento'))
    if fecha > now_local().date() or fecha.year < 2000:
        raise Error('La fecha del evento debe estar entre el año 2000 y hoy.')
    ids = data.get('involucrados', [])
    if isinstance(ids, str):
        try: ids = json.loads(ids)
        except ValueError: raise Error('Seleccione las personas involucradas.')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
        raise Error('Seleccione entre 1 y 100 personas involucradas.')
    ids = sorted({positive_int(i, 'Empleado') for i in ids})
    hora = str(data.get('hora_evento') or '').strip()
    if hora and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hora):
        raise Error('Hora inválida; use HH:MM.')
    if tipo in ('accidente', 'incidente') and not hora:
        raise Error('Indique la hora del evento.')
    details = {k: text_field(data, k, 180, False) for k in DETALLES}
    if tipo == 'inseguro' and details['advertido'] not in ('si', 'no'):
        raise Error('Indique si se advirtió a la persona.')
    if tipo in ('accidente', 'incidente') and not details['lugar']:
        raise Error('Indique el lugar del evento.')
    cat = positive_int(data.get('categoria_id'), 'Categoría') if data.get('categoria_id') else None
    if tipo in ('seguro', 'inseguro') and not cat:
        raise Error('Seleccione una categoría.')
    return dict(tipo=tipo, fecha_evento=fecha.isoformat(), hora_evento=hora or None,
        descripcion=text_field(data, 'descripcion', 8000), categoria_id=cat, detalles=details, involucrados=ids)


def validate_people(c, empresa, ids, reporter=None, historical=False):
    people = {p['id']: p for p in employees(c, empresa, active=not historical)}
    if any(i not in people for i in ids):
        raise Error('Algún empleado no pertenece a la empresa o no está activo.')
    if reporter:
        if reporter['id'] not in people:
            raise Error('Empleado reportante inactivo.', 403)
        branch = people[reporter['id']]['sucursal_id']
        if any(i != reporter['id'] and (branch is None or people[i]['sucursal_id'] != branch) for i in ids):
            raise Error('Solo puede reportar personas de su sucursal.', 403)
    return [people[i] for i in ids]


def category(c, empresa, data):
    if not data['categoria_id']:
        return ''
    cat = db.one(c, "SELECT * FROM sh_catalogos WHERE id=%s AND empresa_id=%s AND clase='categoria' AND activo=1", (data['categoria_id'], empresa))
    if not cat or cat['tipo'] != data['tipo']:
        raise Error('La categoría no corresponde al tipo o está inactiva.')
    return cat['nombre']


def participants(c, event_id, people):
    for p in people:
        db.insert(c, 'sh_involucrados', dict(evento_id=event_id, empleado_id=p['id'],
            nombre=f"{p.get('apellido') or ''} {p.get('nombre') or ''}".strip(), legajo=str(p.get('legajo') or ''),
            **{k: p.get(k) for k in ('sucursal_id','sucursal_nombre','sector_id','sector_nombre','puesto_id','puesto_nombre')}))


def create(empresa, data, files=(), reporter=None, user=None, import_row=None):
    values = parse(data)
    photos = prepare_photos(files)
    try: key = str(UUID(str(data.get('envio_id'))))
    except (ValueError, TypeError, AttributeError): raise Error('envio_id debe ser un UUID.')
    fingerprint = hashlib.sha256(dumps([values, [p['sha256'] for p in photos]]).encode()).hexdigest()
    with db.transaction() as c:
        db.one(c, 'SELECT id FROM empresas WHERE id=%s FOR UPDATE', (empresa,))
        if import_row:
            pending = db.one(c, '''SELECT f.* FROM sh_import_filas f JOIN sh_importaciones i ON i.id=f.importacion_id
                WHERE f.id=%s AND i.empresa_id=%s FOR UPDATE''', (import_row, empresa))
            if not pending or pending['evento_id']:
                raise Error('Fila importada no encontrada o ya resuelta.', 409)
        old = db.one(c, 'SELECT * FROM sh_eventos WHERE empresa_id=%s AND envio_id=%s', (empresa, key))
        if old:
            if old['contenido_hash'] != fingerprint or old['reportante_id'] != (reporter['id'] if reporter else None) or (old['usuario_id'] != user and not (import_row and old['origen']=='importacion')):
                raise Error('La clave de envío ya fue usada con otros datos.', 409)
            if import_row:
                c.execute('UPDATE sh_import_filas SET evento_id=%s WHERE id=%s',(old['id'],import_row))
                audit(c,empresa,user,'vincular_duplicado_importado',dict(import_row=import_row),old['id'])
            return old['id'], False
        people = validate_people(c, empresa, values['involucrados'], reporter, historical=bool(import_row))
        cat_name = category(c, empresa, values)
        event = {k: v for k, v in values.items() if k not in ('involucrados','detalles')}
        event.update(empresa_id=empresa, reportante_id=reporter['id'] if reporter else None, usuario_id=user,
            detalles=dumps(values['detalles']), categoria_nombre=cat_name, envio_id=key, contenido_hash=fingerprint,
            origen='importacion' if import_row else ('mobile' if reporter else 'web'), creado_at=now_local())
        event_id = db.insert(c, 'sh_eventos', event)
        participants(c, event_id, people)
        for p in photos:
            db.insert(c, 'sh_fotos', dict(evento_id=event_id, contenido=p['contenido']))
        if import_row:
            c.execute('UPDATE sh_import_filas SET evento_id=%s WHERE id=%s', (event_id, import_row))
        audit(c, empresa, user, 'crear', dict(datos=values, reportante_id=event['reportante_id'], import_row=import_row), event_id)
        return event_id, True


def access_clause(employee_id, mode='propio'):
    if mode == 'enviados':
        return 'e.reportante_id=%s', [employee_id]
    return "e.estado='aprobado' AND EXISTS(SELECT 1 FROM sh_involucrados i WHERE i.evento_id=e.id AND i.empleado_id=%s)", [employee_id]


def filters_clause(filters):
    where, args = [], []
    for key in ('desde', 'hasta'):
        if filters.get(key):
            where.append('e.fecha_evento' + ('>=' if key == 'desde' else '<=') + '%s')
            args.append(date_field(filters[key]))
    for key, allowed in [('tipo', TIPOS), ('estado', ('pendiente','aprobado','rechazado','anulado'))]:
        if filters.get(key):
            if filters[key] not in allowed: raise Error('Filtro inválido.')
            where.append(f'e.{key}=%s'); args.append(filters[key])
    for key in ('empleado_id','sucursal_id','sector_id','puesto_id'):
        if filters.get(key):
            where.append(f'EXISTS(SELECT 1 FROM sh_involucrados i WHERE i.evento_id=e.id AND i.{key}=%s)')
            args.append(positive_int(filters[key], key))
    return where, args


def history(empresa, filters=None, employee_id=None, mode='propio', page=1, max_id=None):
    where, args = filters_clause(filters or {})
    where.insert(0, 'e.empresa_id=%s'); args.insert(0, empresa)
    if max_id is not None:
        where.append('e.id<=%s'); args.append(max_id)
    if employee_id:
        clause, params = access_clause(employee_id, mode)
        where.append('(' + clause + ')'); args += params
    sql = ' FROM sh_eventos e WHERE ' + ' AND '.join(where)
    with db.transaction() as c:
        total = db.one(c, 'SELECT COUNT(*) total' + sql, tuple(args))['total']
        rows = db.all_rows(c, 'SELECT e.id,e.tipo,e.fecha_evento,e.categoria_nombre,e.estado,e.descripcion,e.revision' + sql +
            ' ORDER BY e.fecha_evento DESC,e.id DESC LIMIT 30 OFFSET %s', tuple(args + [(max(1,page)-1)*30]))
    return dict(items=rows,total=total,page=page,per_page=30)


def detail(empresa, event_id, employee_id=None):
    with db.transaction() as c:
        row = db.one(c, 'SELECT * FROM sh_eventos WHERE id=%s AND empresa_id=%s', (event_id,empresa))
        if not row: raise Error('Registro no encontrado.',404)
        people = db.all_rows(c, 'SELECT * FROM sh_involucrados WHERE evento_id=%s ORDER BY nombre', (event_id,))
        if employee_id and row['reportante_id'] != employee_id and not (row['estado']=='aprobado' and any(p['empleado_id']==employee_id for p in people)):
            raise Error('Registro no encontrado.',404)
        row['involucrados'] = people if not employee_id or row['reportante_id']==employee_id else [p for p in people if p['empleado_id']==employee_id]
        row['detalles'] = json.loads(row['detalles'])
        row['fotos'] = db.all_rows(c, 'SELECT id FROM sh_fotos WHERE evento_id=%s AND activo=1', (event_id,))
        if employee_id:
            # Ni la identidad del denunciante ni las notas de revisión se exponen en mobile.
            for key in ('reportante_id','usuario_id','revisor_id','envio_id','contenido_hash','motivo'):
                row.pop(key,None)
        else:
            row['reportante']=db.one(c,'SELECT legajo,nombre,apellido FROM empleados WHERE id=%s AND empresa_id=%s',(row['reportante_id'],empresa)) if row['reportante_id'] else None
            row['acciones'] = db.all_rows(c, '''SELECT a.*,CONCAT_WS(' ',p.apellido,p.nombre) responsable
                FROM sh_acciones a JOIN empleados p ON p.id=a.responsable_id WHERE a.evento_id=%s''', (event_id,))
            row['auditoria'] = db.all_rows(c, 'SELECT * FROM sh_auditoria WHERE evento_id=%s ORDER BY id DESC', (event_id,))
            row['importacion'] = db.one(c, 'SELECT id,importacion_id,hoja,fila,original FROM sh_import_filas WHERE evento_id=%s', (event_id,))
        return row


def photo(empresa, photo_id, employee_id=None):
    with db.transaction() as c:
        row = db.one(c, '''SELECT f.* FROM sh_fotos f JOIN sh_eventos e ON e.id=f.evento_id
            WHERE f.id=%s AND e.empresa_id=%s AND f.activo=1''', (photo_id,empresa))
    if not row: raise Error('Foto no encontrada.',404)
    detail(empresa,row['evento_id'],employee_id)
    return row


def review(empresa, event_id, user, state, revision, reason):
    if state not in ('aprobado','rechazado','anulado'):
        raise Error('Estado inválido.')
    if state != 'aprobado' and not str(reason or '').strip():
        raise Error('Indique el motivo.')
    with db.transaction() as c:
        row = db.one(c, 'SELECT * FROM sh_eventos WHERE id=%s AND empresa_id=%s FOR UPDATE', (event_id,empresa))
        if not row: raise Error('Registro no encontrado.',404)
        if row['revision'] != positive_int(revision,'Revisión') or row['estado']=='anulado' or (state!='anulado' and row['estado']!='pendiente'):
            raise Error('El registro cambió o ya fue revisado. Actualice la página.',409)
        c.execute('UPDATE sh_eventos SET estado=%s,motivo=%s,revisor_id=%s,revisado_at=%s,revision=revision+1 WHERE id=%s',
            (state,str(reason or '').strip(),user,now_local(),event_id))
        audit(c,empresa,user,state,dict(anterior=row['estado'],motivo=reason),event_id)


def edit(empresa,event_id,user,data,files=()):
    values = parse(data)
    photos = prepare_photos(files)
    with db.transaction() as c:
        row = db.one(c,'SELECT * FROM sh_eventos WHERE id=%s AND empresa_id=%s FOR UPDATE',(event_id,empresa))
        if not row: raise Error('Registro no encontrado.',404)
        if row['estado']=='anulado' or row['revision'] != positive_int(data.get('revision'),'Revisión'):
            raise Error('El registro cambió o está anulado.',409)
        existing_photos={r['id'] for r in db.all_rows(c,'SELECT id FROM sh_fotos WHERE evento_id=%s AND activo=1',(event_id,))}
        remove={positive_int(i,'Foto') for i in data.get('quitar_fotos',[])}
        if not remove<=existing_photos: raise Error('Foto no encontrada en este evento.')
        if len(existing_photos)-len(remove)+len(photos)>5: raise Error('Máximo 5 fotos por evento.')
        for photo_id in remove:
            c.execute('UPDATE sh_fotos SET activo=0 WHERE id=%s',(photo_id,))
        people = validate_people(c,empresa,values['involucrados'],historical=row['origen']=='importacion')
        cat_name = category(c,empresa,values)
        c.execute('''UPDATE sh_eventos SET tipo=%s,fecha_evento=%s,hora_evento=%s,descripcion=%s,
            categoria_id=%s,categoria_nombre=%s,detalles=%s,estado='pendiente',revision=revision+1,
            revisado_at=NULL,revisor_id=NULL,motivo=NULL WHERE id=%s''',
            (values['tipo'],values['fecha_evento'],values['hora_evento'],values['descripcion'],values['categoria_id'],cat_name,dumps(values['detalles']),event_id))
        row['involucrados']=db.all_rows(c,'SELECT * FROM sh_involucrados WHERE evento_id=%s',(event_id,))
        c.execute('DELETE FROM sh_involucrados WHERE evento_id=%s',(event_id,))
        participants(c,event_id,people)
        for p in photos: db.insert(c,'sh_fotos',dict(evento_id=event_id,contenido=p['contenido']))
        audit(c,empresa,user,'editar',dict(anterior=row,nuevo=values,fotos_retiradas=sorted(remove)),event_id)


def rankings(empresa, anio, mes=None, filters=None):
    try:
        anio=int(anio); mes=int(mes) if mes else None
        if not 2000<=anio<=2100 or mes is not None and not 1<=mes<=12: raise ValueError()
    except (ValueError,TypeError): raise Error('Año o mes inválido.')
    start=date(anio,mes or 1,1)
    end=date(anio+1,1,1) if mes in (None,12) else date(anio,mes+1,1)
    conditions=['e.empresa_id=%s',"e.estado='aprobado'",'e.fecha_evento>=%s','e.fecha_evento<%s']
    args=[empresa,start,end]
    for key in ('empleado_id','sucursal_id','sector_id','puesto_id'):
        if (filters or {}).get(key):
            conditions.append(f'i.{key}=%s'); args.append(positive_int(filters[key],key))
    with db.transaction() as c:
        rows=db.all_rows(c,'''SELECT i.empleado_id,MAX(i.nombre) nombre,MAX(i.legajo) legajo,e.tipo,COUNT(*) cantidad
            FROM sh_eventos e JOIN sh_involucrados i ON i.evento_id=e.id WHERE '''+' AND '.join(conditions)+
            ' GROUP BY i.empleado_id,e.tipo ORDER BY cantidad DESC,nombre,i.empleado_id',tuple(args))
        events=db.all_rows(c,'''SELECT e.tipo,COUNT(DISTINCT e.id) cantidad FROM sh_eventos e
            JOIN sh_involucrados i ON i.evento_id=e.id WHERE '''+' AND '.join(conditions)+' GROUP BY e.tipo',tuple(args))
    result={k:[] for k in TIPOS}
    for row in rows:
        group=result[row.pop('tipo')]
        row['posicion']=group[-1]['posicion'] if group and group[-1]['cantidad']==row['cantidad'] else len(group)+1
        group.append(row)
    return dict(anio=anio,mes=mes,rankings=result,eventos=events)


def save_catalog(empresa,user,data,record_id=None):
    clase=data.get('clase'); tipo=data.get('tipo','') if clase=='categoria' else ''
    if clase not in CLASES or clase=='categoria' and tipo not in TIPOS: raise Error('Catálogo inválido.')
    nombre=text_field(data,'nombre',180)
    with db.transaction() as c:
        db.one(c,'SELECT id FROM empresas WHERE id=%s FOR UPDATE',(empresa,))
        if record_id and not db.one(c,'SELECT id FROM sh_catalogos WHERE id=%s AND empresa_id=%s',(record_id,empresa)):
            raise Error('Catálogo no encontrado.',404)
        dup=db.one(c,'SELECT id FROM sh_catalogos WHERE empresa_id=%s AND clase=%s AND tipo=%s AND nombre=%s',(empresa,clase,tipo,nombre))
        if dup and dup['id']!=record_id: raise Error('Ya existe ese catálogo.',409)
        if record_id:
            c.execute('UPDATE sh_catalogos SET nombre=%s,activo=%s WHERE id=%s',(nombre,int(data.get('activo')=='1'),record_id))
        else:
            record_id=db.insert(c,'sh_catalogos',dict(empresa_id=empresa,clase=clase,tipo=tipo,nombre=nombre))
        audit(c,empresa,user,'catalogo',dict(id=record_id,datos=dict(data)))


def save_action(empresa,event_id,user,data,record_id=None):
    description=text_field(data,'descripcion',4000)
    responsable=positive_int(data.get('responsable_id'),'Responsable')
    deadline=date_field(data.get('vencimiento'))
    state=data.get('estado','pendiente')
    evidence=text_field(data,'evidencia',4000,False)
    if state not in ('pendiente','en_curso','cerrada','anulada'): raise Error('Estado de acción inválido.')
    if state in ('cerrada','anulada') and not evidence: raise Error('Indique evidencia de cierre o motivo de anulación.')
    with db.transaction() as c:
        if not db.one(c,'SELECT id FROM sh_eventos WHERE id=%s AND empresa_id=%s FOR UPDATE',(event_id,empresa)):
            raise Error('Registro no encontrado.',404)
        validate_people(c,empresa,[responsable])
        if record_id:
            if not db.one(c,'SELECT id FROM sh_acciones WHERE id=%s AND evento_id=%s',(record_id,event_id)): raise Error('Acción no encontrada.',404)
            c.execute('UPDATE sh_acciones SET descripcion=%s,responsable_id=%s,vencimiento=%s,estado=%s,evidencia=%s WHERE id=%s',
                (description,responsable,deadline,state,evidence,record_id))
        else:
            record_id=db.insert(c,'sh_acciones',dict(evento_id=event_id,descripcion=description,responsable_id=responsable,vencimiento=deadline,estado=state,evidencia=evidence))
        audit(c,empresa,user,'accion_correctiva',dict(id=record_id,datos=dict(data)),event_id)
