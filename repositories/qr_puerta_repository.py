from extensions import get_db


def create(
    *,
    empresa_id: int,
    empresa_nombre: str,
    sucursal_id: int,
    sucursal_nombre: str,
    tipo_marca: str,
    geo_lat: float,
    geo_lon: float,
    tolerancia_m: int,
    vigencia_dias: int,
    vigencia_segundos: int,
    expira_at,
    qr_token: str,
    usuario_id: int | None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO qr_puerta_historial (
                empresa_id,
                empresa_nombre,
                sucursal_id,
                sucursal_nombre,
                tipo_marca,
                geo_lat,
                geo_lon,
                tolerancia_m,
                vigencia_dias,
                vigencia_segundos,
                expira_at,
                qr_token,
                usuario_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                empresa_id,
                empresa_nombre,
                sucursal_id,
                sucursal_nombre,
                tipo_marca,
                geo_lat,
                geo_lon,
                tolerancia_m,
                vigencia_dias,
                vigencia_segundos,
                expira_at,
                qr_token,
                usuario_id,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)
    finally:
        cursor.close()
        db.close()


def get_by_id(historial_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM qr_puerta_historial
            WHERE id = %s
            LIMIT 1
            """,
            (historial_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_recent(limit: int = 30, empresa_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        lim = max(1, min(int(limit), 200))
        if empresa_id:
            cursor.execute(
                """
                SELECT *
                FROM qr_puerta_historial
                WHERE empresa_id = %s
                ORDER BY fecha DESC, id DESC
                LIMIT %s
                """,
                (empresa_id, lim),
            )
        else:
            cursor.execute(
                """
                SELECT *
                FROM qr_puerta_historial
                ORDER BY fecha DESC, id DESC
                LIMIT %s
                """,
                (lim,),
            )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()
