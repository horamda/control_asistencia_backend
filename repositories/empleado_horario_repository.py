from extensions import get_db


def get_actual_by_empleado(empleado_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT eh.*, h.nombre AS horario_nombre, emp.razon_social AS empresa_nombre
            FROM empleado_horarios eh
            JOIN horarios h ON h.id = eh.horario_id
            JOIN empleados e ON e.id = eh.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            WHERE eh.empleado_id = %s
              AND eh.fecha_desde <= CURDATE()
              AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= CURDATE())
            ORDER BY eh.fecha_desde DESC
            LIMIT 1
            """,
            (empleado_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_empleado_fecha(empleado_id: int, fecha: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT eh.*, h.*
            FROM empleado_horarios eh
            JOIN horarios h ON h.id = eh.horario_id
            WHERE eh.empleado_id = %s
              AND eh.fecha_desde <= %s
              AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= %s)
            ORDER BY eh.fecha_desde DESC
            LIMIT 1
            """,
            (empleado_id, fecha, fecha),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_historial(empleado_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT eh.*, h.nombre AS horario_nombre, emp.razon_social AS empresa_nombre
            FROM empleado_horarios eh
            JOIN horarios h ON h.id = eh.horario_id
            JOIN empleados e ON e.id = eh.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            WHERE eh.empleado_id = %s
            ORDER BY eh.fecha_desde DESC, eh.id DESC
            """,
            (empleado_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_asignacion_by_id(asignacion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT eh.*, h.nombre AS horario_nombre
            FROM empleado_horarios eh
            JOIN horarios h ON h.id = eh.horario_id
            WHERE eh.id = %s
            LIMIT 1
            """,
            (asignacion_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def _overlap_exists(cursor, empleado_id: int, fecha_desde: str, fecha_hasta: str | None, exclude_id: int | None = None):
    new_hasta = fecha_hasta or "9999-12-31"
    if exclude_id:
        cursor.execute(
            """
            SELECT 1
            FROM empleado_horarios eh
            WHERE eh.empleado_id = %s
              AND eh.id <> %s
              AND eh.fecha_desde <= %s
              AND COALESCE(eh.fecha_hasta, '9999-12-31') >= %s
            LIMIT 1
            """,
            (empleado_id, exclude_id, new_hasta, fecha_desde),
        )
    else:
        cursor.execute(
            """
            SELECT 1
            FROM empleado_horarios eh
            WHERE eh.empleado_id = %s
              AND eh.fecha_desde <= %s
              AND COALESCE(eh.fecha_hasta, '9999-12-31') >= %s
            LIMIT 1
            """,
            (empleado_id, new_hasta, fecha_desde),
        )
    return cursor.fetchone() is not None


def has_overlap(empleado_id: int, fecha_desde: str, fecha_hasta: str | None, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        return _overlap_exists(cursor, empleado_id, fecha_desde, fecha_hasta, exclude_id)
    finally:
        cursor.close()
        db.close()


def asignar_horario(empleado_id: int, horario_id: int, fecha_desde: str, empresa_id: int):
    return create_asignacion(empleado_id, horario_id, fecha_desde, None, empresa_id)


def create_asignacion(empleado_id: int, horario_id: int, fecha_desde: str, fecha_hasta: str | None, empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        cursor.execute(
            """
            SELECT id
            FROM empleados
            WHERE id = %s
            FOR UPDATE
            """,
            (empleado_id,),
        )
        cursor.execute(
            """
            SELECT id
            FROM empleado_horarios
            WHERE empleado_id = %s
            FOR UPDATE
            """,
            (empleado_id,),
        )
        if _overlap_exists(cursor, empleado_id, fecha_desde, fecha_hasta):
            raise ValueError("La asignacion se superpone con otra vigente en el rango.")

        cursor.execute(
            """
            INSERT INTO empleado_horarios (empresa_id, empleado_id, horario_id, fecha_desde, fecha_hasta)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (empresa_id, empleado_id, horario_id, fecha_desde, fecha_hasta),
        )
        asignacion_id = cursor.lastrowid
        db.commit()
        return asignacion_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def update_asignacion(
    asignacion_id: int,
    empleado_id: int,
    horario_id: int,
    fecha_desde: str,
    fecha_hasta: str | None,
    empresa_id: int,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        cursor.execute(
            """
            SELECT id
            FROM empleados
            WHERE id = %s
            FOR UPDATE
            """,
            (empleado_id,),
        )
        cursor.execute(
            """
            SELECT id
            FROM empleado_horarios
            WHERE id = %s
              AND empleado_id = %s
            FOR UPDATE
            """,
            (asignacion_id, empleado_id),
        )
        if not cursor.fetchone():
            raise ValueError("Asignacion no encontrada.")

        cursor.execute(
            """
            SELECT id
            FROM empleado_horarios
            WHERE empleado_id = %s
            FOR UPDATE
            """,
            (empleado_id,),
        )
        if _overlap_exists(cursor, empleado_id, fecha_desde, fecha_hasta, exclude_id=asignacion_id):
            raise ValueError("La asignacion se superpone con otra vigente en el rango.")

        cursor.execute(
            """
            UPDATE empleado_horarios
            SET empresa_id = %s,
                horario_id = %s,
                fecha_desde = %s,
                fecha_hasta = %s
            WHERE id = %s
              AND empleado_id = %s
            """,
            (empresa_id, horario_id, fecha_desde, fecha_hasta, asignacion_id, empleado_id),
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def delete_asignacion(asignacion_id: int, empleado_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM empleado_horarios
            WHERE id = %s
              AND empleado_id = %s
            """,
            (asignacion_id, empleado_id),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def get_empleados_activos_en_fecha(fecha: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT e.id AS empleado_id, e.empresa_id, eh.horario_id
            FROM empleados e
            JOIN empleado_horarios eh ON eh.empleado_id = e.id
            WHERE e.activo = 1
              AND eh.fecha_desde <= %s
              AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= %s)
            """,
            (fecha, fecha),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()
