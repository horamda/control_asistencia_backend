"""Small, scoped datasets for monthly attendance; no UI pagination cap."""
from extensions import get_db


def approved_justifications(*, fecha_desde, fecha_hasta, empresa_id=None, sucursal_id=None, sector_id=None):
    where = ["j.estado = 'aprobada'", "COALESCE(j.fecha_hasta,j.fecha) >= %s", "COALESCE(j.fecha_desde,j.fecha) <= %s"]
    params = [fecha_desde, fecha_hasta]
    for column, value in [('empresa_id', empresa_id), ('sucursal_id', sucursal_id), ('sector_id', sector_id)]:
        if value:
            where.append(f"e.{column} = %s")
            params.append(value)
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT j.empleado_id,j.fecha,j.fecha_desde,j.fecha_hasta,j.estado FROM justificaciones j JOIN empleados e ON e.id=j.empleado_id WHERE " + ' AND '.join(where), tuple(params))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()
