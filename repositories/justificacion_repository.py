from extensions import get_db


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                j.*,
                e.nombre,
                e.apellido,
                a.fecha AS asistencia_fecha,
                emp.razon_social AS empresa_nombre,
                u.usuario AS resuelto_by_usuario,
                (
                    SELECT le.id
                    FROM legajo_eventos le
                    WHERE le.justificacion_id = j.id
                    ORDER BY le.id DESC
                    LIMIT 1
                ) AS legajo_evento_id,
                (
                    SELECT COUNT(*)
                    FROM legajo_eventos le
                    JOIN legajo_evento_adjuntos a2
                      ON a2.evento_id = le.id
                     AND a2.estado = 'activo'
                    WHERE le.justificacion_id = j.id
                ) AS adjuntos_count
            FROM justificaciones j
            JOIN empleados e ON e.id = j.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN usuarios u ON u.id = j.resuelto_by_usuario_id
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            ORDER BY j.created_at DESC, j.id DESC
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(
    page: int,
    per_page: int,
    empleado_id: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    search: str | None = None,
    estado: str | None = None,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if empleado_id:
            where.append("j.empleado_id = %s")
            params.append(empleado_id)
        if fecha_desde:
            where.append("COALESCE(j.fecha_hasta, j.fecha) >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("COALESCE(j.fecha_desde, j.fecha) <= %s")
            params.append(fecha_hasta)
        if search:
            where.append("(e.apellido LIKE %s OR e.nombre LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        if estado:
            where.append("j.estado = %s")
            params.append(estado)
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(sucursal_id)
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(sector_id)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"""
            SELECT
                j.*,
                e.nombre,
                e.apellido,
                a.fecha AS asistencia_fecha,
                emp.razon_social AS empresa_nombre,
                s.nombre AS sucursal_nombre,
                sec.nombre AS sector_nombre,
                u.usuario AS resuelto_by_usuario,
                (
                    SELECT le.id
                    FROM legajo_eventos le
                    WHERE le.justificacion_id = j.id
                    ORDER BY le.id DESC
                    LIMIT 1
                ) AS legajo_evento_id,
                (
                    SELECT COUNT(*)
                    FROM legajo_eventos le
                    JOIN legajo_evento_adjuntos a2
                      ON a2.evento_id = le.id
                     AND a2.estado = 'activo'
                    WHERE le.justificacion_id = j.id
                ) AS adjuntos_count
            FROM justificaciones j
            JOIN empleados e ON e.id = j.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN usuarios u ON u.id = j.resuelto_by_usuario_id
            {where_sql}
            ORDER BY j.created_at DESC, j.id DESC
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM justificaciones j
            JOIN empleados e ON e.id = j.empleado_id
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            LEFT JOIN usuarios u ON u.id = j.resuelto_by_usuario_id
            {where_sql}
        """, params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(justificacion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                j.*,
                a.fecha AS asistencia_fecha,
                u.usuario AS resuelto_by_usuario,
                (
                    SELECT le.id
                    FROM legajo_eventos le
                    WHERE le.justificacion_id = j.id
                    ORDER BY le.id DESC
                    LIMIT 1
                ) AS legajo_evento_id,
                (
                    SELECT COUNT(*)
                    FROM legajo_eventos le
                    JOIN legajo_evento_adjuntos a2
                      ON a2.evento_id = le.id
                     AND a2.estado = 'activo'
                    WHERE le.justificacion_id = j.id
                ) AS adjuntos_count
            FROM justificaciones j
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            LEFT JOIN usuarios u ON u.id = j.resuelto_by_usuario_id
            WHERE j.id = %s
        """, (justificacion_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO justificaciones
            (
                empleado_id,
                asistencia_id,
                fecha,
                fecha_desde,
                fecha_hasta,
                motivo,
                archivo,
                estado
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.get("empleado_id"),
            data.get("asistencia_id"),
            data.get("fecha"),
            data.get("fecha_desde"),
            data.get("fecha_hasta"),
            data.get("motivo"),
            data.get("archivo"),
            data.get("estado")
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(justificacion_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE justificaciones
            SET
                empleado_id = %s,
                asistencia_id = %s,
                fecha = %s,
                fecha_desde = %s,
                fecha_hasta = %s,
                motivo = %s,
                archivo = %s,
                estado = %s
            WHERE id = %s
        """, (
            data.get("empleado_id"),
            data.get("asistencia_id"),
            data.get("fecha"),
            data.get("fecha_desde"),
            data.get("fecha_hasta"),
            data.get("motivo"),
            data.get("archivo"),
            data.get("estado"),
            justificacion_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(justificacion_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM justificaciones
            WHERE id = %s
        """, (justificacion_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def get_by_asistencia(asistencia_id: int) -> list:
    """Returns all justificaciones linked to a given asistencia_id."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, empleado_id, asistencia_id, fecha, fecha_desde, fecha_hasta, estado
            FROM justificaciones
            WHERE asistencia_id = %s
        """, (asistencia_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_fecha(empleado_id: int, fecha: str) -> list:
    """Returns all justificaciones for an employee and operative date."""
    return get_by_rango(empleado_id, fecha, fecha)


def get_by_rango(empleado_id: int, fecha_desde: str, fecha_hasta: str) -> list:
    """Returns all justificaciones that overlap the given date range."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, empleado_id, asistencia_id, fecha, fecha_desde, fecha_hasta, estado
            FROM justificaciones
            WHERE empleado_id = %s
              AND COALESCE(fecha_desde, fecha) <= %s
              AND COALESCE(fecha_hasta, fecha) >= %s
        """, (empleado_id, fecha_hasta, fecha_desde))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def update_estado(
    justificacion_id: int,
    estado: str,
    *,
    resuelto_by_usuario_id: int | None = None,
    comentario_resolucion: str | None = None,
    motivo_rechazo: str | None = None,
) -> None:
    """Minimal update: only changes the estado field."""
    db = get_db()
    cursor = db.cursor()
    try:
        resolved_by = int(resuelto_by_usuario_id) if resuelto_by_usuario_id else None
        is_resolved = estado in {"aprobada", "rechazada"}
        comentario = str(comentario_resolucion or "").strip() or None
        rechazo = str(motivo_rechazo or "").strip() or None
        cursor.execute("""
            UPDATE justificaciones
            SET estado = %s,
                resuelto_by_usuario_id = %s,
                resuelto_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                comentario_resolucion = %s,
                motivo_rechazo = %s,
                notificado_empleado_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                visto_por_empleado_at = NULL
            WHERE id = %s
        """, (
            estado,
            resolved_by if is_resolved else None,
            1 if is_resolved else 0,
            comentario if is_resolved else None,
            rechazo if estado == "rechazada" else None,
            1 if is_resolved else 0,
            justificacion_id,
        ))
        db.commit()
    finally:
        cursor.close()
        db.close()


def marcar_vista_por_empleado(justificacion_id: int, empleado_id: int) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE justificaciones
            SET visto_por_empleado_at = NOW()
            WHERE id = %s
              AND empleado_id = %s
              AND estado IN ('aprobada', 'rechazada')
        """, (int(justificacion_id), int(empleado_id)))
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()
