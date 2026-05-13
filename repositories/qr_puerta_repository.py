import hashlib

from extensions import get_db


def _token_hash(qr_token: str) -> str:
    return hashlib.sha256(str(qr_token or "").encode("utf-8")).hexdigest()


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
                qr_token_hash,
                usuario_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                _token_hash(qr_token),
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


def get_by_token(qr_token: str):
    token = str(qr_token or "").strip()
    if not token:
        return None
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM qr_puerta_historial
            WHERE qr_token_hash = %s OR qr_token = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (_token_hash(token), token),
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


def deactivate(historial_id: int, usuario_id: int | None, motivo: str | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE qr_puerta_historial
            SET activo = 0,
                inactivado_at = NOW(),
                inactivado_by_usuario = %s,
                inactivado_motivo = %s
            WHERE id = %s
              AND activo = 1
            """,
            (usuario_id, str(motivo or "").strip() or None, historial_id),
        )
        db.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        db.close()
