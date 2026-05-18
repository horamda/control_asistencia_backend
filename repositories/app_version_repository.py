from extensions import get_db


def get_version_config(platform: str) -> dict | None:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                platform,
                version_minima,
                version_recomendada,
                url_descarga,
                mensaje
            FROM app_version_config
            WHERE activo = 1
              AND platform IN (%s, 'all')
            ORDER BY
                CASE platform WHEN %s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (platform, platform),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_all() -> list:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, platform, version_minima, version_recomendada,
                   url_descarga, mensaje, activo, updated_at
            FROM app_version_config
            ORDER BY FIELD(platform, 'android', 'ios', 'all'), id
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(config_id: int) -> dict | None:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM app_version_config WHERE id = %s",
            (config_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict) -> int:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO app_version_config
              (platform, version_minima, version_recomendada, url_descarga, mensaje, activo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data.get("platform", "android"),
            data.get("version_minima") or "1.0.0",
            data.get("version_recomendada") or "1.0.0",
            data.get("url_descarga") or None,
            data.get("mensaje") or None,
            1 if data.get("activo", True) else 0,
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(config_id: int, data: dict) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE app_version_config
            SET platform = %s,
                version_minima = %s,
                version_recomendada = %s,
                url_descarga = %s,
                mensaje = %s,
                activo = %s
            WHERE id = %s
        """, (
            data.get("platform", "android"),
            data.get("version_minima") or "1.0.0",
            data.get("version_recomendada") or "1.0.0",
            data.get("url_descarga") or None,
            data.get("mensaje") or None,
            1 if data.get("activo", True) else 0,
            config_id,
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(config_id: int) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM app_version_config WHERE id = %s", (config_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
