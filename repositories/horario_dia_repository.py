from extensions import get_db


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT hd.*, h.nombre AS horario_nombre
            FROM horario_dias hd
            JOIN horarios h ON h.id = hd.horario_id
            ORDER BY h.nombre, hd.dia_semana
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(dia_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM horario_dias
            WHERE id = %s
        """, (dia_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_id_with_horario(dia_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT hd.*, h.nombre AS horario_nombre, h.empresa_id
            FROM horario_dias hd
            JOIN horarios h ON h.id = hd.horario_id
            WHERE hd.id = %s
        """, (dia_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_horario(horario_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM horario_dias
            WHERE horario_id = %s
            ORDER BY dia_semana
        """, (horario_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_horario_dia(horario_id: int, dia_semana: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM horario_dias
            WHERE horario_id = %s
              AND dia_semana = %s
            LIMIT 1
        """, (horario_id, dia_semana))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def exists_dia(horario_id: int, dia_semana: int, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        if exclude_id:
            cursor.execute("""
                SELECT 1
                FROM horario_dias
                WHERE horario_id = %s
                  AND dia_semana = %s
                  AND id <> %s
                LIMIT 1
            """, (horario_id, dia_semana, exclude_id))
        else:
            cursor.execute("""
                SELECT 1
                FROM horario_dias
                WHERE horario_id = %s
                  AND dia_semana = %s
                LIMIT 1
            """, (horario_id, dia_semana))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO horario_dias (horario_id, dia_semana)
            VALUES (%s,%s)
        """, (
            data.get("horario_id"),
            data.get("dia_semana")
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(dia_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE horario_dias
            SET horario_id = %s,
                dia_semana = %s
            WHERE id = %s
        """, (
            data.get("horario_id"),
            data.get("dia_semana"),
            dia_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(dia_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM horario_dias
            WHERE id = %s
        """, (dia_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
