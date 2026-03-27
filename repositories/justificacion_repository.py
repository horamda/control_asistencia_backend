from extensions import get_db


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT j.*, e.nombre, e.apellido, a.fecha AS asistencia_fecha, emp.razon_social AS empresa_nombre
            FROM justificaciones j
            JOIN empleados e ON e.id = j.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            ORDER BY j.created_at DESC, j.id DESC
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(page: int, per_page: int, empleado_id: int | None = None, fecha_desde: str | None = None, fecha_hasta: str | None = None, search: str | None = None, estado: str | None = None):
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
            where.append("a.fecha >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("a.fecha <= %s")
            params.append(fecha_hasta)
        if search:
            where.append("(e.apellido LIKE %s OR e.nombre LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        if estado:
            where.append("j.estado = %s")
            params.append(estado)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"""
            SELECT j.*, e.nombre, e.apellido, a.fecha AS asistencia_fecha, emp.razon_social AS empresa_nombre
            FROM justificaciones j
            JOIN empleados e ON e.id = j.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
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
            SELECT *
            FROM justificaciones
            WHERE id = %s
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
                motivo,
                archivo,
                estado
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            data.get("empleado_id"),
            data.get("asistencia_id"),
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
                motivo = %s,
                archivo = %s,
                estado = %s
            WHERE id = %s
        """, (
            data.get("empleado_id"),
            data.get("asistencia_id"),
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
            SELECT id, empleado_id, asistencia_id, estado
            FROM justificaciones
            WHERE asistencia_id = %s
        """, (asistencia_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def update_estado(justificacion_id: int, estado: str) -> None:
    """Minimal update: only changes the estado field."""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE justificaciones
            SET estado = %s
            WHERE id = %s
        """, (estado, justificacion_id))
        db.commit()
    finally:
        cursor.close()
        db.close()
