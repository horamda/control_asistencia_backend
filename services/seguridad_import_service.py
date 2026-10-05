"""Archivo original inmutable, filas recuperables y resolución explícita."""
import hashlib
import io
import json
import unicodedata
import zipfile
from datetime import date, datetime, time
from uuid import uuid5, NAMESPACE_URL
from openpyxl import load_workbook
from services import seguridad_service as s


def key(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',str(value or '')) if not unicodedata.combining(c)).lower().split())


def read_file(file):
    if not file or not (file.filename or '').lower().endswith('.xlsx'):
        raise s.Error('Seleccione el Excel de respuestas (.xlsx).')
    raw=file.read(10*1024*1024+1)
    if not raw or len(raw)>10*1024*1024: raise s.Error('Máximo 10 MB por archivo.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(i.file_size for i in z.infolist())>50*1024*1024 or len(z.infolist())>2000:
                raise s.Error('El contenido descomprimido del archivo es demasiado grande.')
        workbook=load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
        result=[]
        for sheet in workbook:
            if (sheet.max_row or 0)>10000 or (sheet.max_column or 0)>200:
                raise s.Error('Máximo 10.000 filas y 200 columnas por hoja.')
            headers=None
            for number,row in enumerate(sheet.values,1):
                if number>10000 or len(row)>200: raise s.Error('Máximo 10.000 filas y 200 columnas por hoja.')
                values=[v.isoformat() if isinstance(v,(date,datetime,time)) else v for v in row]
                if not any(v not in (None,'') for v in values): continue
                normalized=[key(v) for v in values]
                if 'marca temporal' in normalized and 'que va a notificar' in normalized:
                    headers=values; continue
                # La cabecera de grupos permanece en el archivo, no es una respuesta.
                if headers is None: continue
                result.append(dict(hoja=sheet.title,fila=number,original=dict(encabezados=headers,celdas=values)))
                if len(result)>5000: raise s.Error('Máximo 5.000 respuestas por importación.')
        workbook.close()
    except s.Error: raise
    except Exception as exc: raise s.Error('No se pudo leer el Excel. Use el archivo de respuestas con sus encabezados originales.') from exc
    if not result: raise s.Error('No se encontró la cabecera del formulario ni respuestas.')
    return raw,result


def suggest(original,people,catalogs):
    cells=original['celdas']; headers=original['encabezados']
    def get(label,index=0):
        matches=[i for i,h in enumerate(headers) if key(h)==key(label)]
        return cells[matches[index]] if len(matches)>index and matches[index]<len(cells) else None
    kind={'comportamiento seguro':'seguro','comportamiento inseguro':'inseguro'}.get(key(get('Que va a notificar')),'')
    errors=[]
    if not kind:
        errors.append('Defina el tipo; accidente e incidente estaban agrupados.' if key(get('Que va a notificar'))=='accidente-incidente' else 'Fila sin tipo informado: revisar datos originales.')
    name=get('Apellido y nombre completo de la persona a informar')
    if not name:
        name=get('Nombre Completo de quien comete la infracción',1 if kind=='seguro' else 0)
    matches=[p for p in people if key(name) in (key(f"{p['apellido']} {p['nombre']}"),key(f"{p['nombre']} {p['apellido']}"))]
    ids=[matches[0]['id']] if len(matches)==1 else []
    if not ids: errors.append('Vincule la persona con su legajo; no hay una coincidencia única.')
    date_value=get('Fecha que se observa la condición insegura-comportamiento inseguro') if kind=='inseguro' else get('Fecha del evento',1 if kind=='seguro' else 0)
    fecha=str(date_value or '')[:10]
    try:
        parsed=date.fromisoformat(fecha)
        if parsed.year<2000 or parsed>s.now_local().date(): raise ValueError()
    except ValueError:
        fecha=''; errors.append('Corrija la fecha del evento.')
    name_cat=get('Infracción que cometió') if kind=='inseguro' else get('Comportamiento Seguro') if kind=='seguro' else None
    cats=[c for c in catalogs if c['clase']=='categoria' and c['tipo']==kind and c['activo'] and key(c['nombre'])==key(name_cat)]
    cat=cats[0]['id'] if len(cats)==1 else None
    if kind and not cat: errors.append('Seleccione o cree la categoría en Catálogos.')
    desc=get('Comentarios') if kind=='inseguro' else get('Comentarios, describir la tarea que se realizo') if kind=='seguro' else get('Descripción del evento')
    if not desc: errors.append('Complete la descripción; no se inventa a partir de la categoría.')
    value=dict(tipo=kind,persona_original=str(name or ''),fecha_evento=fecha,hora_evento=str(get('Horario del Evento') or '')[:5],
        descripcion=str(desc or ''),categoria_id=cat,involucrados=ids,
        advertido=key(get('Se advirtió a la persona que estaba cometiendo el acto?')),
        lugar=get('Lugar del evento') or '',clasificacion=get('¿Es SIF (hubo riesgo de muerte), FAI(lesión leve), MTI(lesión moderada),  MDI(lesión grave), o LTI(lesión muy grave)?') or '',
        atencion=get('Requiero de') or '',lesion=get('Tipo de Lesión') or '',parte_cuerpo=get('Parte del Cuerpo lesionado') or '')
    if kind=='inseguro' and value['advertido'] not in ('si','no'): errors.append('Indique si se advirtió a la persona.')
    if not errors:
        try: s.parse(value)
        except s.Error as exc: errors.append(str(exc))
    return value,errors


def stage(empresa,user,file):
    raw,rows=read_file(file)
    sha=hashlib.sha256(raw).hexdigest()
    with s.db.transaction() as c:
        s.db.one(c,'SELECT id FROM empresas WHERE id=%s FOR UPDATE',(empresa,))
        old=s.db.one(c,'SELECT id FROM sh_importaciones WHERE empresa_id=%s AND sha256=%s',(empresa,sha))
        if old: return old['id']
        people=s.employees(c,empresa,False)
        cats=s.db.all_rows(c,'SELECT * FROM sh_catalogos WHERE empresa_id=%s',(empresa,))
        batch=s.db.insert(c,'sh_importaciones',dict(empresa_id=empresa,usuario_id=user,nombre=file.filename[:255],archivo=raw,sha256=sha,creado_at=s.now_local()))
        for row in rows:
            proposed,errors=suggest(row['original'],people,cats)
            s.db.insert(c,'sh_import_filas',dict(importacion_id=batch,hoja=row['hoja'],fila=row['fila'],original=s.dumps(row['original']),propuesta=s.dumps(proposed),errores=s.dumps(errors)))
        s.audit(c,empresa,user,'importar_archivo',dict(importacion_id=batch,filas=len(rows),sha256=sha))
        return batch


def batch(empresa,batch_id,page=1):
    with s.db.transaction() as c:
        row=s.db.one(c,'SELECT id,nombre,creado_at FROM sh_importaciones WHERE id=%s AND empresa_id=%s',(batch_id,empresa))
        if not row: raise s.Error('Importación no encontrada.',404)
        row['totales']=s.db.one(c,'SELECT COUNT(*) total,SUM(evento_id IS NOT NULL) resueltas FROM sh_import_filas WHERE importacion_id=%s',(batch_id,))
        row['filas']=s.db.all_rows(c,'SELECT id,hoja,fila,propuesta,errores,evento_id FROM sh_import_filas WHERE importacion_id=%s ORDER BY fila,id LIMIT 30 OFFSET %s',(batch_id,(page-1)*30))
        for f in row['filas']:
            f['propuesta']=json.loads(f['propuesta']); f['errores']=json.loads(f['errores'])
        return row


def pending(empresa,row_id):
    with s.db.transaction() as c:
        row=s.db.one(c,'''SELECT f.* FROM sh_import_filas f JOIN sh_importaciones i ON i.id=f.importacion_id
            WHERE f.id=%s AND i.empresa_id=%s''',(row_id,empresa))
        if not row: raise s.Error('Fila no encontrada.',404)
        row['original']=json.loads(row['original'])
        cats=s.db.all_rows(c,'SELECT * FROM sh_catalogos WHERE empresa_id=%s',(empresa,))
        row['propuesta'],row['errores']=suggest(row['original'],s.employees(c,empresa,False),cats)
        # La misma respuesta en una nueva exportación no vuelve a contar como evento.
        original=row['original']
        canonical=[]
        for index in range(max(len(original['encabezados']),len(original['celdas']))):
            h=original['encabezados'][index] if index<len(original['encabezados']) else None
            v=original['celdas'][index] if index<len(original['celdas']) else None
            if h or v is not None:
                canonical.append((key(h) or f'columna_{index}',str(v).strip() if v is not None else ''))
        source_hash=hashlib.sha256(s.dumps(canonical).encode()).hexdigest()
        row['propuesta']['envio_id']=str(uuid5(NAMESPACE_URL,f'sh-import:{empresa}:{source_hash}'))
        return row


def import_ready(empresa,batch_id,user):
    batch(empresa,batch_id)
    with s.db.transaction() as c:
        ids=s.db.all_rows(c,'SELECT id FROM sh_import_filas WHERE importacion_id=%s AND evento_id IS NULL',(batch_id,))
    ok=0; unresolved=0
    for r in ids:
        row=pending(empresa,r['id'])
        if row['errores']:
            unresolved+=1; continue
        try:
            _,created=s.create(empresa,row['propuesta'],user=user,import_row=r['id'])
            ok+=int(created)
        except s.Error as exc:
            unresolved+=1
            with s.db.transaction() as c:
                c.execute('UPDATE sh_import_filas SET errores=%s WHERE id=%s',(s.dumps([str(exc)]),r['id']))
    return ok,unresolved
