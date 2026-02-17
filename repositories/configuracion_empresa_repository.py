from extensions import get_db


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT c.*, e.razon_social
            FROM configuracion_empresa c
            JOIN empresas e ON e.id = c.empresa_id
            ORDER BY e.razon_social
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_empresa_id(empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM configuracion_empresa
            WHERE empresa_id = %s
        """, (empresa_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def upsert(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO configuracion_empresa
            (
                empresa_id,
                requiere_qr,
                requiere_foto,
                requiere_geo,
                tolerancia_global
            )
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                requiere_qr = VALUES(requiere_qr),
                requiere_foto = VALUES(requiere_foto),
                requiere_geo = VALUES(requiere_geo),
                tolerancia_global = VALUES(tolerancia_global)
        """, (
            data.get("empresa_id"),
            1 if data.get("requiere_qr") else 0,
            1 if data.get("requiere_foto") else 0,
            1 if data.get("requiere_geo") else 0,
            data.get("tolerancia_global")
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
