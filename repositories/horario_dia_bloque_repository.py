from extensions import get_db


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT hdb.*, hd.dia_semana, h.nombre AS horario_nombre, h.id AS horario_id
            FROM horario_dia_bloques hdb
            JOIN horario_dias hd ON hd.id = hdb.horario_dia_id
            JOIN horarios h ON h.id = hd.horario_id
            ORDER BY h.nombre, hd.dia_semana, hdb.orden
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_horario_dia(horario_dia_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM horario_dia_bloques
            WHERE horario_dia_id = %s
            ORDER BY orden
        """, (horario_dia_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(bloque_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT hdb.*, hd.horario_id, hd.dia_semana
            FROM horario_dia_bloques hdb
            JOIN horario_dias hd ON hd.id = hdb.horario_dia_id
            WHERE hdb.id = %s
        """, (bloque_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def exists_orden(horario_dia_id: int, orden: int, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        if exclude_id:
            cursor.execute("""
                SELECT 1
                FROM horario_dia_bloques
                WHERE horario_dia_id = %s
                  AND orden = %s
                  AND id <> %s
                LIMIT 1
            """, (horario_dia_id, orden, exclude_id))
        else:
            cursor.execute("""
                SELECT 1
                FROM horario_dia_bloques
                WHERE horario_dia_id = %s
                  AND orden = %s
                LIMIT 1
            """, (horario_dia_id, orden))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO horario_dia_bloques
            (
                empresa_id,
                horario_dia_id,
                orden,
                hora_entrada,
                hora_salida
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("horario_dia_id"),
            data.get("orden"),
            data.get("hora_entrada"),
            data.get("hora_salida")
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(bloque_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE horario_dia_bloques
            SET
                empresa_id = %s,
                horario_dia_id = %s,
                orden = %s,
                hora_entrada = %s,
                hora_salida = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("horario_dia_id"),
            data.get("orden"),
            data.get("hora_entrada"),
            data.get("hora_salida"),
            bloque_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(bloque_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM horario_dia_bloques
            WHERE id = %s
        """, (bloque_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
