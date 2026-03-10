from extensions import get_db


def _ensure_adjuntos_db_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS legajo_evento_adjuntos_db (
            adjunto_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
            data LONGBLOB NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT fk_legajo_adjuntos_db_adjunto
              FOREIGN KEY (adjunto_id) REFERENCES legajo_evento_adjuntos (id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def create_adjunto(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        storage_backend = str(data.get("storage_backend") or "local").strip().lower() or "local"
        storage_data = data.get("storage_data")
        cursor.execute(
            """
            INSERT INTO legajo_evento_adjuntos
            (
                evento_id,
                empresa_id,
                empleado_id,
                nombre_original,
                mime_type,
                extension,
                tamano_bytes,
                sha256,
                storage_backend,
                storage_ruta,
                estado,
                created_by_usuario_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("evento_id"),
                data.get("empresa_id"),
                data.get("empleado_id"),
                data.get("nombre_original"),
                data.get("mime_type"),
                data.get("extension"),
                data.get("tamano_bytes"),
                data.get("sha256"),
                storage_backend,
                data.get("storage_ruta"),
                data.get("estado") or "activo",
                data.get("created_by_usuario_id"),
            ),
        )
        adjunto_id = int(cursor.lastrowid)
        if storage_backend == "db":
            if not storage_data:
                raise ValueError("Adjunto en DB sin contenido binario.")
            _ensure_adjuntos_db_table(cursor)
            cursor.execute(
                """
                INSERT INTO legajo_evento_adjuntos_db (adjunto_id, data)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE data = VALUES(data)
                """,
                (adjunto_id, storage_data),
            )
        db.commit()
        return adjunto_id
    finally:
        cursor.close()
        db.close()


def get_adjuntos_by_evento(evento_id: int, include_deleted: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql = "" if include_deleted else "AND a.estado = 'activo'"
        cursor.execute(
            f"""
            SELECT
                a.id,
                a.evento_id,
                a.empresa_id,
                a.empleado_id,
                a.nombre_original,
                a.mime_type,
                a.extension,
                a.tamano_bytes,
                a.sha256,
                a.storage_backend,
                a.storage_ruta,
                a.estado,
                a.created_by_usuario_id,
                a.created_at,
                a.deleted_by_usuario_id,
                a.deleted_at,
                u.usuario AS created_by_usuario
            FROM legajo_evento_adjuntos a
            LEFT JOIN usuarios u ON u.id = a.created_by_usuario_id
            WHERE a.evento_id = %s
              {where_sql}
            ORDER BY a.created_at DESC, a.id DESC
            """,
            (evento_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_adjunto_by_id(adjunto_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.*,
                e.estado AS evento_estado
            FROM legajo_evento_adjuntos a
            JOIN legajo_eventos e ON e.id = a.evento_id
            WHERE a.id = %s
            """,
            (adjunto_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def mark_deleted(adjunto_id: int, deleted_by_usuario_id: int | None):
    db = get_db()
    cursor = db.cursor()
    try:
        _ensure_adjuntos_db_table(cursor)
        cursor.execute(
            """
            UPDATE legajo_evento_adjuntos
            SET
                estado = 'eliminado',
                deleted_by_usuario_id = %s,
                deleted_at = NOW()
            WHERE id = %s
            """,
            (deleted_by_usuario_id, adjunto_id),
        )
        if cursor.rowcount > 0:
            cursor.execute(
                "DELETE FROM legajo_evento_adjuntos_db WHERE adjunto_id = %s",
                (adjunto_id,),
            )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def get_adjunto_data_by_id(adjunto_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        _ensure_adjuntos_db_table(cursor)
        cursor.execute(
            """
            SELECT data
            FROM legajo_evento_adjuntos_db
            WHERE adjunto_id = %s
            """,
            (adjunto_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return bytes(row[0] or b"")
    finally:
        cursor.close()
        db.close()
