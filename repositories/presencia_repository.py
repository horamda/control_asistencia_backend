"""Lectura de fichadas y nombres para la consulta de personas por sucursal."""

from extensions import get_db


def get_daily_presence(fecha, hora, empresa_id=None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    scope = " AND e.empresa_id = %s" if empresa_id else ""
    params = (empresa_id,) if empresa_id else ()
    try:
        cursor.execute(
            "SELECT e.id, e.nombre, e.apellido, e.empresa_id, emp.razon_social AS empresa, e.sucursal_id, e.sector_id, e.modalidad, "
            "s.nombre AS sucursal, sec.nombre AS sector "
            "FROM empleados e JOIN empresas emp ON emp.id = e.empresa_id "
            "LEFT JOIN sucursales s ON s.id = e.sucursal_id "
            "LEFT JOIN sectores sec ON sec.id = e.sector_id "
            "WHERE e.activo = 1 AND emp.activa = 1" + scope,
            params,
        )
        empleados = cursor.fetchall()
        # Marcas detalladas primero. Las asistencias históricas/manuales sin
        # marcas se incorporan como respaldo, sin duplicar sus movimientos.
        cursor.execute(
            """
            SELECT m.empleado_id AS empleado_id, m.hora AS hora, m.accion AS accion, m.id AS id,
                   m.metodo AS metodo, m.gps_ok AS gps_ok
            FROM asistencia_marcas m JOIN empleados e ON e.id = m.empleado_id
            WHERE e.activo = 1 AND m.fecha = %s AND m.hora <= %s
              AND m.accion IN ('ingreso', 'egreso')
            """ + scope + """
            UNION ALL
            SELECT a.empleado_id, a.hora_entrada AS hora, 'ingreso' AS accion, a.id,
                   a.metodo_entrada AS metodo, a.gps_ok_entrada AS gps_ok
            FROM asistencias a JOIN empleados e ON e.id = a.empleado_id
            WHERE e.activo = 1 AND a.fecha = %s AND a.hora_entrada <= %s
              AND NOT EXISTS (SELECT 1 FROM asistencia_marcas m
                              WHERE m.empleado_id = a.empleado_id AND m.fecha = a.fecha)
            """ + scope + """
            UNION ALL
            SELECT a.empleado_id, a.hora_salida AS hora, 'egreso' AS accion, a.id,
                   a.metodo_salida AS metodo, a.gps_ok_salida AS gps_ok
            FROM asistencias a JOIN empleados e ON e.id = a.empleado_id
            WHERE e.activo = 1 AND a.fecha = %s AND a.hora_salida <= %s
              AND NOT EXISTS (SELECT 1 FROM asistencia_marcas m
                              WHERE m.empleado_id = a.empleado_id AND m.fecha = a.fecha)
            """ + scope + " ORDER BY hora, id, accion DESC",
            (fecha, hora, *params, fecha, hora, *params, fecha, hora, *params),
        )
        return empleados, cursor.fetchall()
    finally:
        cursor.close()
        db.close()
