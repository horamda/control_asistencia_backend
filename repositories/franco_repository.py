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
            SELECT f.*, e.nombre, e.apellido
            FROM francos f
            JOIN empleados e ON e.id = f.empleado_id
            ORDER BY f.fecha DESC, f.id DESC
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(franco_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM francos
            WHERE id = %s
        """, (franco_id,))
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
            INSERT INTO francos (empresa_id, empleado_id, fecha, motivo)
            VALUES (%s,%s,%s,%s)
        """, (
            empresa_id,
            empleado_id,
            data.get("fecha"),
            data.get("motivo")
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(franco_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        empleado_id = data.get("empleado_id")
        empresa_id = data.get("empresa_id") or _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")
        cursor.execute("""
            UPDATE francos
            SET empresa_id = %s,
                empleado_id = %s,
                fecha = %s,
                motivo = %s
            WHERE id = %s
        """, (
            empresa_id,
            empleado_id,
            data.get("fecha"),
            data.get("motivo"),
            franco_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(franco_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM francos
            WHERE id = %s
        """, (franco_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
