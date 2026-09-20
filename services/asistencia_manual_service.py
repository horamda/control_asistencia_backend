"""Atomic manual attendance changes. Original values are retained in corrections."""
import json
from extensions import get_db
from repositories import asistencia_repository as summaries
from repositories import asistencia_marca_repository as marks
from utils.asistencia import validar_asistencia
from web.asistencias.planilla_helpers import _to_hhmm, _parse_hhmm


def _lock(cur, asistencia_id):
    cur.execute('SELECT * FROM asistencias WHERE id=%s FOR UPDATE', (asistencia_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError('Asistencia no encontrada.')
    cur.execute('SELECT * FROM asistencia_marcas WHERE asistencia_id=%s ORDER BY hora,id FOR UPDATE', (asistencia_id,))
    return row, cur.fetchall()


def _audit(cur, aid, actor, action, before, after):
    cur.execute('''INSERT INTO asistencia_correcciones
        (asistencia_id,usuario_id,accion,antes,despues) VALUES (%s,%s,%s,%s,%s)''',
        (aid, actor, action, json.dumps(before, default=str, ensure_ascii=False),
         json.dumps(after, default=str, ensure_ascii=False)))


def _new_mark(db, row, action, hour, observation=None):
    return marks.create(empresa_id=row['empresa_id'], empleado_id=row['empleado_id'],
        asistencia_id=row['id'], fecha=str(row['fecha'])[:10], hora=hour,
        accion=action, metodo='manual', tipo_marca='jornada', lat=None, lon=None,
        foto=None, gps_ok=None, gps_distancia_m=None, gps_tolerancia_m=None,
        gps_ref_lat=None, gps_ref_lon=None, estado=row.get('estado'),
        observaciones=observation, _db=db)


def save_manual(data, *, asistencia_id=None, actor=None):
    db=get_db(); cur=db.cursor(dictionary=True)
    try:
        before, previous = (None, []) if asistencia_id is None else _lock(cur, asistencia_id)
        by_action={a:[m for m in previous if m['accion']==a] for a in ('ingreso','egreso')}
        if any(len(v)>1 for v in by_action.values()) or any(m.get('tipo_marca') not in (None,'','jornada') for m in previous):
            raise ValueError('Esta jornada tiene varias marcas o movimientos especiales. Corregi la marca concreta desde la planilla diaria; el resumen no se modifico.')
        # Unlinked or other summaries on the same day need individual review.
        cur.execute('SELECT id FROM asistencia_marcas WHERE empleado_id=%s AND fecha=%s AND (asistencia_id IS NULL OR asistencia_id<>%s) LIMIT 1 FOR UPDATE',
                    (data['empleado_id'],data['fecha'],asistencia_id or 0))
        if cur.fetchone():
            raise ValueError('Hay otras marcas en esa fecha. Corregi la jornada desde la planilla diaria.')
        cur.execute('SELECT id FROM asistencias WHERE empleado_id=%s AND fecha=%s AND id<>%s LIMIT 1 FOR UPDATE',
                    (data['empleado_id'],data['fecha'],asistencia_id or 0))
        if cur.fetchone():
            raise ValueError('Ya existe otra asistencia para esa persona y fecha. Edita el registro existente.')
        payload=dict(data)
        _,state=validar_asistencia(payload['empleado_id'],payload['fecha'],payload.get('hora_entrada'),payload.get('hora_salida'))
        payload['estado']=state or ('ok' if payload.get('hora_entrada') or payload.get('hora_salida') else 'ausente')
        for side in ('entrada','salida'):
            if not before:
                payload['metodo_'+side]='manual' if payload.get('hora_'+side) else None
        if asistencia_id is None:
            asistencia_id=summaries.create(payload,_db=db)
        else:
            summaries.update(asistencia_id,payload,_db=db)
        row,_=_lock(cur,asistencia_id)
        for action,side in [('ingreso','entrada'),('egreso','salida')]:
            hour=payload.get('hora_'+side)
            existing=by_action[action][0] if by_action[action] else None
            if not hour:
                if existing: marks.delete_by_id(existing['id'],_db=db)
            elif existing:
                changed = (_to_hhmm(existing['hora'])!=_to_hhmm(hour) or
                           existing['empleado_id']!=row['empleado_id'] or str(existing['fecha'])[:10]!=str(row['fecha'])[:10])
                cur.execute('''UPDATE asistencia_marcas SET hora=%s,empresa_id=%s,empleado_id=%s,fecha=%s,
                    observaciones=%s,corregida_manualmente=CASE WHEN %s THEN 1 ELSE corregida_manualmente END WHERE id=%s''',
                    (hour,row['empresa_id'],row['empleado_id'],row['fecha'],payload.get('observaciones'),int(changed),existing['id']))
            else:
                _new_mark(db,row,action,hour,payload.get('observaciones'))
        summaries.sync_from_asistencia_marcas(asistencia_id,_db=db)
        after,new_marks=_lock(cur,asistencia_id)
        _audit(cur,asistencia_id,actor,'editar' if before else 'crear',{'resumen':before,'marcas':previous},{'resumen':after,'marcas':new_marks})
        db.commit()
        return asistencia_id
    except Exception:
        db.rollback(); raise
    finally:
        cur.close(); db.close()


def change_mark(*, marca_id=None, asistencia_id=None, action='editar', hora=None, accion=None, observaciones=None, actor=None):
    if action != 'eliminar':
        hora = _parse_hhmm(hora)
    db=get_db();cur=db.cursor(dictionary=True)
    try:
        if marca_id is not None:
            cur.execute('SELECT asistencia_id FROM asistencia_marcas WHERE id=%s',(marca_id,))
            mark=cur.fetchone()
            if not mark or not mark.get('asistencia_id'):
                raise ValueError('Marca sin resumen vinculado. Requiere revision antes de corregirla.')
            asistencia_id=mark['asistencia_id']
        before,previous=_lock(cur,asistencia_id)
        if marca_id is not None and not any(m['id']==marca_id for m in previous):
            raise ValueError('La marca cambio; recarga la planilla.')
        if action=='eliminar':
            marks.delete_by_id(marca_id,_db=db)
        elif action=='crear':
            # Preserve the other endpoint when editing a virtual legacy summary.
            if not previous:
                for other, side in [('ingreso','entrada'),('egreso','salida')]:
                    if other != accion and before.get('hora_'+side) is not None:
                        legacy_id = _new_mark(db,before,other,_to_hhmm(before['hora_'+side]),before.get('observaciones'))
                        cur.execute('UPDATE asistencia_marcas SET metodo=%s WHERE id=%s',
                                    (before.get('metodo_'+side) or 'manual',legacy_id))
            if accion not in ('ingreso','egreso'): raise ValueError('Accion invalida.')
            marca_id=_new_mark(db,before,accion,hora,observaciones)
        else:
            marks.update_basic(marca_id,hora=hora,accion=accion,observaciones=observaciones,_db=db)
            cur.execute('UPDATE asistencia_marcas SET corregida_manualmente=1 WHERE id=%s',(marca_id,))
        summaries.sync_from_asistencia_marcas(asistencia_id,_db=db)
        after,new_marks=_lock(cur,asistencia_id)
        _audit(cur,asistencia_id,actor,action+'_marca',{'resumen':before,'marcas':previous},{'resumen':after,'marcas':new_marks})
        db.commit();return marca_id
    except Exception:
        db.rollback();raise
    finally:
        cur.close();db.close()


def delete_manual(asistencia_id, *, actor=None):
    db=get_db();cur=db.cursor(dictionary=True)
    try:
        before,previous=_lock(cur,asistencia_id)
        _audit(cur,asistencia_id,actor,'eliminar',{'resumen':before,'marcas':previous},None)
        cur.execute('DELETE FROM asistencia_marcas WHERE asistencia_id=%s',(asistencia_id,))
        summaries.delete(asistencia_id,_db=db)
        db.commit()
    except Exception:
        db.rollback();raise
    finally:
        cur.close();db.close()
