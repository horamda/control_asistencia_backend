"""Habilitación explícita por empleado y exclusión por puesto."""
from extensions import get_db


def get_config():
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute('''SELECT h.empleado_id FROM vacaciones_compensatorios_empleados h
            JOIN empleados e ON e.id=h.empleado_id AND e.empresa_id=h.empresa_id
            WHERE h.habilitado=1 AND e.activo=1''')
        empleados = {r['empleado_id'] for r in c.fetchall()}
        c.execute('SELECT puesto_id FROM vacaciones_compensatorios_puestos WHERE bloqueado=1')
        puestos = {r['puesto_id'] for r in c.fetchall()}
        c.execute('''SELECT DISTINCT e.id FROM empleados e
            JOIN vacaciones_compensatorios_puestos p ON p.empresa_id=e.empresa_id AND p.bloqueado=1
            WHERE p.puesto_id=e.puesto_id OR EXISTS (
                SELECT 1 FROM empleado_puestos ep WHERE ep.empleado_id=e.id
                AND ep.puesto_id=p.puesto_id AND ep.activo=1)''')
        bloqueados = {r['id'] for r in c.fetchall()}
        return empleados, puestos, bloqueados
    finally:
        c.close()
        db.close()


def habilitado(empleado_id):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute('''SELECT e.id FROM empleados e
            JOIN vacaciones_compensatorios_empleados h
              ON h.empleado_id=e.id AND h.empresa_id=e.empresa_id AND h.habilitado=1
            WHERE e.id=%s AND e.activo=1 AND NOT EXISTS (
                SELECT 1 FROM vacaciones_compensatorios_puestos p
                WHERE p.empresa_id=e.empresa_id AND p.bloqueado=1 AND (
                    p.puesto_id=e.puesto_id OR EXISTS (
                        SELECT 1 FROM empleado_puestos ep WHERE ep.empleado_id=e.id
                        AND ep.puesto_id=p.puesto_id AND ep.activo=1)))''', (empleado_id,))
        return c.fetchone() is not None
    finally:
        c.close()
        db.close()


def save_selection(kind, ids, value):
    # Solo los IDs seleccionados cambian; no se reemplaza toda la configuración.
    if kind not in ('empleados', 'puestos') or not ids:
        raise ValueError('Seleccione al menos un registro.')
    column, flag = ('empleado_id', 'habilitado') if kind == 'empleados' else ('puesto_id', 'bloqueado')
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        for record_id in sorted(set(ids)):
            c.execute(f'SELECT id, empresa_id FROM {kind} WHERE id=%s FOR UPDATE', (record_id,))
            row = c.fetchone()
            if not row:
                raise ValueError('Registro no encontrado. Actualice la página.')
            c.execute(f'''INSERT INTO vacaciones_compensatorios_{kind} ({column},empresa_id,{flag})
                VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE empresa_id=VALUES(empresa_id), {flag}=VALUES({flag})''',
                (record_id, row['empresa_id'], int(value)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        c.close()
        db.close()
