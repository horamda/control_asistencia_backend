from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT h.*, e.razon_social AS empresa_nombre
                FROM horarios h
                JOIN empresas e ON e.id = h.empresa_id
                ORDER BY e.razon_social, h.nombre
            """)
        else:
            cursor.execute("""
                SELECT h.*, e.razon_social AS empresa_nombre
                FROM horarios h
                JOIN empresas e ON e.id = h.empresa_id
                WHERE h.activo = 1
                ORDER BY e.razon_social, h.nombre
            """)
        rows = cursor.fetchall()
        return rows
    finally:
        cursor.close()
        db.close()


def get_by_id(horario_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM horarios
            WHERE id = %s
        """, (horario_id,))
        row = cursor.fetchone()
        return row
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO horarios
            (
                empresa_id,
                nombre,
                tolerancia_min,
                descripcion,
                activo
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            data.get("tolerancia_min"),
            data.get("descripcion"),
            1 if data.get("activo") else 0
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(horario_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE horarios
            SET
                empresa_id = %s,
                nombre = %s,
                tolerancia_min = %s,
                descripcion = %s,
                activo = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            data.get("tolerancia_min"),
            data.get("descripcion"),
            1 if data.get("activo") else 0,
            horario_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(horario_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE horarios
            SET activo = %s
            WHERE id = %s
        """, (1 if activo else 0, horario_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
