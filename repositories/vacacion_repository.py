from extensions import get_db


def _get_empresa_id_for_empleado(cursor, empleado_id: int | None):
    if not empleado_id:
        return None
    cursor.execute("""
        SELECT empresa_id
        FROM empleados
        WHERE id = %s
        LIMIT 1
    """, (empleado_id,))
    row = cursor.fetchone()
    if isinstance(row, dict):
        return row.get("empresa_id")
    return row[0] if row else None


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT v.*, e.nombre, e.apellido
            FROM vacaciones v
            JOIN empleados e ON e.id = v.empleado_id
            ORDER BY v.fecha_desde DESC, v.id DESC
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(vacacion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM vacaciones
            WHERE id = %s
        """, (vacacion_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        empleado_id = data.get("empleado_id")
        empresa_id = data.get("empresa_id") or _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")
        cursor.execute("""
            INSERT INTO vacaciones (empresa_id, empleado_id, fecha_desde, fecha_hasta, observaciones)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            empresa_id,
            empleado_id,
            data.get("fecha_desde"),
            data.get("fecha_hasta"),
            data.get("observaciones")
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(vacacion_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        empleado_id = data.get("empleado_id")
        empresa_id = data.get("empresa_id") or _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")
        cursor.execute("""
            UPDATE vacaciones
            SET empresa_id = %s,
                empleado_id = %s,
                fecha_desde = %s,
                fecha_hasta = %s,
                observaciones = %s
            WHERE id = %s
        """, (
            empresa_id,
            empleado_id,
            data.get("fecha_desde"),
            data.get("fecha_hasta"),
            data.get("observaciones"),
            vacacion_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(vacacion_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM vacaciones
            WHERE id = %s
        """, (vacacion_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
