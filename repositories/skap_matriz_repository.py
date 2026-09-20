from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

from extensions import get_db
from services.skap_excel_service import name_key, normalize


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


@contextmanager
def transaction():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        yield cursor
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def _rows(sql, args=()):
    with transaction() as c:
        c.execute(sql, args)
        return c.fetchall()


def employee_options(empresa_id):
    return _rows('''SELECT e.id,e.empresa_id,e.legajo,e.nombre,e.apellido,e.activo,e.sucursal_id,e.sector_id,
                   e.reporta_a_empleado_id,s.nombre AS sucursal_nombre
                   FROM empleados e LEFT JOIN sucursales s ON s.id=e.sucursal_id
                   WHERE e.empresa_id=%s ORDER BY e.apellido,e.nombre''', (empresa_id,))


def branch_options(empresa_id):
    return _rows('SELECT id,empresa_id,nombre FROM sucursales WHERE empresa_id=%s ORDER BY nombre', (empresa_id,))


def name_aliases(empresa_id):
    return {r['nombre_clave']:r['empleado_id'] for r in _rows('SELECT nombre_clave,empleado_id FROM skap_matriz_aliases WHERE empresa_id=%s',(empresa_id,))}


def save_preview(payload, empresa_id, usuario_id):
    with transaction() as c:
        c.execute('''INSERT INTO skap_matriz_importaciones (empresa_id,usuario_id,archivo,sha256,contenido)
                     VALUES (%s,%s,%s,%s,%s)''', (empresa_id, usuario_id, payload['archivo'], payload['sha256'], dumps(payload)))
        return c.lastrowid


def get_import(import_id, empresa_id):
    rows = _rows('SELECT * FROM skap_matriz_importaciones WHERE id=%s AND empresa_id=%s', (import_id, empresa_id))
    if not rows:
        return None
    row = rows[0]
    row['payload'] = json.loads(row['contenido'])
    return row


def list_imports(empresa_id):
    return _rows('''SELECT id,archivo,estado,created_at,resultado FROM skap_matriz_importaciones
                   WHERE empresa_id=%s ORDER BY id DESC LIMIT 100''', (empresa_id,))


def _scope(actor, alias='ev', own=False):
    # A linked employee is mandatory for employee/supervisor scope. Never trust a query-string ID.
    conditions = [f'{alias}.empresa_id=%s']
    args = [actor['empresa_id']]
    role = actor.get('rol')
    if own or role not in {'admin', 'rrhh', 'supervisor'}:
        conditions.append(f'{alias}.empleado_id=%s')
        args.append(actor.get('empleado_id') or -1)
    elif role == 'supervisor':
        conditions.append(f'''({alias}.empleado_id=%s OR {alias}.empleado_id IN
                           (SELECT id FROM empleados WHERE reporta_a_empleado_id=%s AND empresa_id=%s))''')
        args.extend([actor.get('empleado_id') or -1, actor.get('empleado_id') or -1, actor['empresa_id']])
    return conditions, args


def list_evaluations(actor, *, own=False, anio=None, sucursal_id=None, empleado_id=None, rol=None):
    where, args = _scope(actor, own=own)
    for column, value in [('anio', anio), ('sucursal_id', sucursal_id), ('empleado_id', empleado_id), ('rol_clave', rol)]:
        if value is not None:
            where.append(f'ev.{column}=%s')
            args.append(value)
    rows = _rows(f'''SELECT ev.*, e.legajo,e.apellido,e.nombre,s.nombre AS sucursal_nombre
                    FROM skap_matriz_evaluaciones ev JOIN empleados e ON e.id=ev.empleado_id
                    JOIN sucursales s ON s.id=ev.sucursal_id WHERE {' AND '.join(where)}
                    ORDER BY ev.anio DESC,e.apellido,e.nombre,ev.rol''', tuple(args))
    for row in rows:
        payload = json.loads(row.pop('contenido'))
        row['resumen'] = payload['resumen']
    return rows


def get_evaluation(evaluation_id, actor, *, own=False):
    where, args = _scope(actor, own=own)
    where.append('ev.id=%s')
    args.append(evaluation_id)
    rows = _rows(f'''SELECT ev.*,e.legajo,e.apellido,e.nombre,e.reporta_a_empleado_id,s.nombre AS sucursal_nombre,
                    i.archivo FROM skap_matriz_evaluaciones ev JOIN empleados e ON e.id=ev.empleado_id
                    JOIN sucursales s ON s.id=ev.sucursal_id JOIN skap_matriz_importaciones i ON i.id=ev.importacion_id
                    WHERE {' AND '.join(where)}''', tuple(args))
    if not rows:
        return None
    row = rows[0]
    row['payload'] = json.loads(row.pop('contenido'))
    row['acciones'] = _rows('''SELECT a.*,CONCAT(e.apellido,' ',e.nombre) AS responsable
                              FROM skap_matriz_acciones a LEFT JOIN empleados e ON e.id=a.responsable_empleado_id
                              WHERE a.evaluacion_id=%s ORDER BY a.criticidad,a.id''', (evaluation_id,))
    return row


def response_hash(ev):
    records = [{k: r.get(k) for k in ('competencia','bloque','criticidad','estandar','estado','puntaje')} for r in ev['respuestas']]
    return hashlib.sha256(dumps(records).encode()).hexdigest()


def commit_import(import_id, payload, actor, selected):
    """One atomic selection. Repeated natural keys are skipped only when all responses agree."""
    created, skipped = [], []
    with transaction() as c:
        c.execute('SELECT estado FROM skap_matriz_importaciones WHERE id=%s AND empresa_id=%s FOR UPDATE', (import_id, actor['empresa_id']))
        batch = c.fetchone()
        if not batch or batch['estado'] != 'vista_previa':
            raise ValueError('Esta importación ya fue aplicada o revertida.')
        for ev in payload['evaluaciones']:
            if ev['clave'] not in selected:
                continue
            if ev.get('vinculo') != 'resuelto' or ev.get('empresa_id') != actor['empresa_id']:
                raise ValueError('Hay personas seleccionadas sin un legajo válido.')
            c.execute('SELECT sector_id FROM empleados WHERE id=%s AND empresa_id=%s FOR UPDATE', (ev['empleado_id'],actor['empresa_id']))
            employee = c.fetchone()
            c.execute('SELECT id FROM sucursales WHERE id=%s AND empresa_id=%s', (ev['sucursal_id'],actor['empresa_id']))
            if not employee or not c.fetchone():
                raise ValueError('El empleado o la sucursal cambiaron; revise la vista previa.')
            role_key = normalize(ev['rol'])
            alias_key = ' '.join(name_key(ev['nombre_original']))
            if ev.get('alias_confirmado'):
                c.execute('SELECT empleado_id FROM skap_matriz_aliases WHERE empresa_id=%s AND nombre_clave=%s', (actor['empresa_id'],alias_key))
                alias = c.fetchone()
                if alias and alias['empleado_id'] != ev['empleado_id']:
                    raise ValueError('El nombre ya está vinculado a otro legajo; revise la equivalencia.')
                if not alias:
                    c.execute('INSERT INTO skap_matriz_aliases (empresa_id,nombre_clave,empleado_id) VALUES (%s,%s,%s)',(actor['empresa_id'],alias_key,ev['empleado_id']))
            digest = response_hash(ev)
            c.execute('''SELECT id,contenido_sha256 FROM skap_matriz_evaluaciones
                         WHERE empresa_id=%s AND empleado_id=%s AND sucursal_id=%s AND rol_clave=%s AND anio=%s FOR UPDATE''',
                      (actor['empresa_id'],ev['empleado_id'],ev['sucursal_id'],role_key,ev['anio']))
            existing = c.fetchone()
            if existing:
                if existing['contenido_sha256'] != digest:
                    raise ValueError(f"Ya existe otra evaluación con distintos puntajes para legajo {ev['legajo']}, {ev['rol']}, {ev['anio']}.")
                skipped.append(ev['clave'])
                continue
            # Store only this person's data in the evaluation snapshot.
            snapshot = {k: v for k, v in ev.items() if k != 'candidatos'}
            c.execute('''INSERT INTO skap_matriz_evaluaciones
                      (importacion_id,empresa_id,empleado_id,sucursal_id,sector_id,rol,rol_clave,anio,
                       nombre_original,hoja,contenido,contenido_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                      (import_id,actor['empresa_id'],ev['empleado_id'],ev['sucursal_id'],employee['sector_id'],ev['rol'],role_key,
                       ev['anio'],ev['nombre_original'],ev['hoja'],dumps(snapshot),digest))
            evaluation_id = c.lastrowid
            created.append(evaluation_id)
            for response in ev['respuestas']:
                if response['estado'] == 'evaluado' and response['puntaje'] < response['estandar']:
                    c.execute('''INSERT INTO skap_matriz_acciones (evaluacion_id,competencia,criticidad,accion)
                                 VALUES (%s,%s,%s,%s)''', (evaluation_id,response['competencia'],response['criticidad'],
                                 'Reforzar '+response['competencia']))
        if not selected or not (created or skipped):
            raise ValueError('Seleccione al menos una evaluación resuelta.')
        result = {'creadas': created, 'duplicadas_omitidas': skipped, 'no_seleccionadas': len(payload['evaluaciones'])-len(selected)}
        c.execute('''UPDATE skap_matriz_importaciones SET estado='aplicada',contenido=%s,resultado=%s,aplicado_at=CURRENT_TIMESTAMP
                     WHERE id=%s''', (dumps(payload),dumps(result),import_id))
        _audit(c, actor, import_id, 'importar', result)
    return result


def _audit(c, actor, import_id, event, detail):
    c.execute('INSERT INTO skap_matriz_auditoria (usuario_id,importacion_id,evento,detalle) VALUES (%s,%s,%s,%s)',
              (actor.get('id'),import_id,event,dumps({'origen':actor.get('origen','panel'),**detail})))


def revert_import(import_id, actor):
    with transaction() as c:
        c.execute('SELECT estado FROM skap_matriz_importaciones WHERE id=%s AND empresa_id=%s FOR UPDATE',(import_id,actor['empresa_id']))
        batch = c.fetchone()
        if not batch or batch['estado'] != 'aplicada':
            raise ValueError('La importación no está aplicada.')
        c.execute('''SELECT a.id FROM skap_matriz_acciones a JOIN skap_matriz_evaluaciones e ON e.id=a.evaluacion_id
                     WHERE e.importacion_id=%s AND a.updated_at IS NOT NULL FOR UPDATE''',(import_id,))
        if c.fetchall():
            raise ValueError('Existen acciones con seguimiento. La reversión requiere conservar primero esos cambios.')
        c.execute('DELETE FROM skap_matriz_evaluaciones WHERE importacion_id=%s',(import_id,))
        count = c.rowcount
        c.execute("UPDATE skap_matriz_importaciones SET estado='revertida',revertido_at=CURRENT_TIMESTAMP WHERE id=%s",(import_id,))
        _audit(c,actor,import_id,'revertir',{'evaluaciones_eliminadas':count})
        return count


def update_action(evaluation, action_id, data, actor):
    with transaction() as c:
        c.execute('SELECT id FROM skap_matriz_importaciones WHERE id=%s FOR UPDATE',(evaluation['importacion_id'],))
        c.fetchone()
        c.execute('SELECT * FROM skap_matriz_acciones WHERE id=%s AND evaluacion_id=%s FOR UPDATE',(action_id,evaluation['id']))
        before = c.fetchone()
        if not before:
            raise ValueError('Acción no encontrada en esta evaluación.')
        c.execute('''UPDATE skap_matriz_acciones SET accion=%s,responsable_empleado_id=%s,fecha_inicio=%s,fecha_fin=%s,
                     estado=%s,progreso=%s,comentarios=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s AND evaluacion_id=%s''',
                  (data['accion'],data['responsable_empleado_id'],data['fecha_inicio'],data['fecha_fin'],data['estado'],
                   data['progreso'],data['comentarios'],action_id,evaluation['id']))
        _audit(c,actor,evaluation['importacion_id'],'editar_accion',{'antes':before,'despues':data})
