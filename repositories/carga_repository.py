"""Consultas del modulo. Las escrituras usan una unica transaccion del servicio."""
from contextlib import contextmanager
from extensions import get_db


@contextmanager
def transaction(*, read_only=False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        yield cursor
        # Pooled connection close resets the read transaction. SELECT does not
        # need an additional COMMIT round trip before returning it to the pool.
        if not read_only:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def one(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchone()


def all_rows(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchall()


def insert(cursor, table, data):
    # Identificadores exclusivamente internos, nunca tomados del request.
    columns = ', '.join(data)
    cursor.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join(['%s'] * len(data))})", tuple(data.values()))
    return cursor.lastrowid


def catalogs(empresa_id):
    with transaction(read_only=True) as c:
        return {
            'camiones': all_rows(c, 'SELECT t.*, s.nombre sucursal_nombre FROM carga_camiones t JOIN sucursales s ON s.id=t.sucursal_id WHERE t.empresa_id=%s ORDER BY t.numero', (empresa_id,)),
            'horarios': all_rows(c, 'SELECT h.*, s.nombre sucursal_nombre FROM carga_horarios h LEFT JOIN sucursales s ON s.id=h.sucursal_id WHERE h.empresa_id=%s ORDER BY h.tipo, h.vigente_desde DESC', (empresa_id,)),
            'sucursales': all_rows(c, 'SELECT id, nombre, activa FROM sucursales WHERE empresa_id=%s ORDER BY nombre', (empresa_id,)),
            'puestos': all_rows(c, 'SELECT p.id, p.nombre, (cp.puesto_id IS NOT NULL) habilitado FROM puestos p LEFT JOIN carga_puestos cp ON cp.puesto_id=p.id AND cp.empresa_id=p.empresa_id WHERE p.empresa_id=%s AND p.activo=1 ORDER BY p.nombre', (empresa_id,)),
        }


def history(empresa_id, filters, *, empleado_id=None, page=1, per_page=30, max_id=None):
    where, args = ['v.empresa_id=%s'], [empresa_id]
    if max_id is not None:
        where.append('v.id<=%s')
        args.append(max_id)
    if empleado_id is not None:
        where.append('v.empleado_id=%s')
        args.append(empleado_id)
    for key in ('camion_id', 'sucursal_empleado_id', 'tipo', 'valida', 'en_horario'):
        if filters.get(key) not in (None, ''):
            where.append(f'v.{key}=%s')
            args.append(filters[key])
    for key, op in (('desde', '>='), ('hasta', '<=')):
        if filters.get(key):
            where.append(f'v.fecha {op} %s')
            args.append(filters[key])
    if filters.get('q'):
        where.append('(v.legajo LIKE %s OR v.empleado_nombre LIKE %s OR v.consolidado LIKE %s)')
        args.extend([f"%{filters['q']}%"] * 3)
    clause = ' AND '.join(where)
    with transaction(read_only=True) as c:
        total = one(c, f'SELECT COUNT(*) total FROM carga_validaciones v WHERE {clause}', tuple(args))['total']
        rows = all_rows(c, f'''SELECT v.*, (SELECT COUNT(*) FROM carga_fotos f WHERE f.validacion_id=v.id) fotos_cantidad
            FROM carga_validaciones v WHERE {clause} ORDER BY v.registrado_at DESC, v.id DESC LIMIT %s OFFSET %s''', (*args, per_page, (page - 1) * per_page))
    for row in rows:
        row.pop('envio_hash', None)
        row.pop('envio_id', None)
    return rows, total


def detail(registro_id, empresa_id, empleado_id=None):
    with transaction() as c:
        row = one(c, 'SELECT * FROM carga_validaciones WHERE id=%s AND empresa_id=%s', (registro_id, empresa_id))
        if not row or (empleado_id is not None and row['empleado_id'] != empleado_id):
            return None
        row['fotos'] = all_rows(c, 'SELECT id FROM carga_fotos WHERE validacion_id=%s ORDER BY id', (registro_id,))
        row.pop('envio_hash', None)
        row.pop('envio_id', None)
        return row


def photo(foto_id, empresa_id, empleado_id=None):
    with transaction() as c:
        where = ' AND v.empleado_id=%s' if empleado_id is not None else ''
        args = (foto_id, empresa_id, empleado_id) if empleado_id is not None else (foto_id, empresa_id)
        return one(c, f'''SELECT f.contenido FROM carga_fotos f JOIN carga_validaciones v ON v.id=f.validacion_id
            WHERE f.id=%s AND v.empresa_id=%s {where}''', args)
