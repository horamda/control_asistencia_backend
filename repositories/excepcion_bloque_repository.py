from extensions import get_db


def get_by_excepcion(excepcion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM excepcion_bloques
            WHERE excepcion_id = %s
            ORDER BY orden
        """, (excepcion_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(bloque_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT eb.*, ex.empleado_id, ex.fecha, ex.tipo, ex.empresa_id
            FROM excepcion_bloques eb
            JOIN empleado_excepciones ex ON ex.id = eb.excepcion_id
            WHERE eb.id = %s
        """, (bloque_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def exists_orden(excepcion_id: int, orden: int, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        if exclude_id:
            cursor.execute("""
                SELECT 1
                FROM excepcion_bloques
                WHERE excepcion_id = %s
                  AND orden = %s
                  AND id <> %s
                LIMIT 1
            """, (excepcion_id, orden, exclude_id))
        else:
            cursor.execute("""
                SELECT 1
                FROM excepcion_bloques
                WHERE excepcion_id = %s
                  AND orden = %s
                LIMIT 1
            """, (excepcion_id, orden))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO excepcion_bloques
            (
                empresa_id,
                excepcion_id,
                orden,
                hora_entrada,
                hora_salida
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("excepcion_id"),
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
            UPDATE excepcion_bloques
            SET
                empresa_id = %s,
                excepcion_id = %s,
                orden = %s,
                hora_entrada = %s,
                hora_salida = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("excepcion_id"),
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
            DELETE FROM excepcion_bloques
            WHERE id = %s
        """, (bloque_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
