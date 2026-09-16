"""Web dashboard aggregates sharing the same scope and registration dates."""
import datetime as dt

from extensions import get_db
from repositories.feedback_repository import _build_where


def get_dashboard_data(*, desde, hasta, sector_id=None, sucursal_ids=None, empleado_activo=None):
    where, params = _build_where(sector_id=sector_id, sucursal_ids=sucursal_ids, empleado_activo=empleado_activo)
    where += (" AND " if where else "WHERE ") + "f.created_at >= %s AND f.created_at < %s"
    params = (*params, desde, hasta + dt.timedelta(days=1))
    base = "FROM feedbacks f JOIN empleados ee ON ee.id = f.empleado_id LEFT JOIN feedback_motivos m ON m.id = f.motivo_id"
    due = "COALESCE(f.fecha_limite, TIMESTAMP(f.fecha_vencimiento, '23:59:59'))"
    pending = "COALESCE(f.estado, 'pendiente') <> 'resuelto'"
    counts = f"""
        COUNT(*) AS total,
        SUM(f.estado = 'resuelto') AS resueltos,
        SUM({pending} AND NOW() <= {due}) AS pendientes,
        SUM({pending} AND NOW() > {due}) AS vencidos,
        SUM(f.estado = 'resuelto' AND f.resuelto_at <= {due}) AS resueltos_en_sla,
        SUM(f.estado = 'resuelto' AND f.resuelto_at > {due}) AS resueltos_fuera_sla,
        SUM({pending} AND {due} IS NULL) AS sin_plazo,
        COUNT(DISTINCT f.empleado_id) AS empleados_con_carga
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT {counts} {base} {where}", params)
        summary = {key: int(value or 0) for key, value in (cursor.fetchone() or {}).items()}
        cursor.execute(f"SELECT DATE_FORMAT(f.created_at, '%Y-%m') AS mes, COUNT(*) AS total {base} {where} GROUP BY mes ORDER BY mes", params)
        months = cursor.fetchall()
        cursor.execute(f"SELECT COALESCE(f.sucursal_id, ee.sucursal_id) AS sucursal_id, {counts} {base} {where} GROUP BY COALESCE(f.sucursal_id, ee.sucursal_id)", params)
        branches = cursor.fetchall()
        cursor.execute(f"""SELECT f.motivo_id, COALESCE(m.nombre, f.motivo_nombre_snapshot, 'Sin motivo') AS motivo_nombre,
            COUNT(*) AS total, SUM(f.estado = 'resuelto') AS resueltos
            {base} {where} GROUP BY f.motivo_id, motivo_nombre ORDER BY total DESC, motivo_nombre LIMIT 5""", params)
        reasons = cursor.fetchall()
        cursor.execute(f"""SELECT ee.id AS empleado_id, ee.apellido, ee.nombre, ee.legajo, COUNT(*) AS total
            {base} {where} GROUP BY ee.id, ee.apellido, ee.nombre, ee.legajo
            ORDER BY total DESC, ee.apellido, ee.nombre, ee.id LIMIT 10""", params)
        return dict(resumen=summary, meses=months, sucursales=branches, top_motivos=reasons, ranking=cursor.fetchall())
    finally:
        cursor.close()
        db.close()
