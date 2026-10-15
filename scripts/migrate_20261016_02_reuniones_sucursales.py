"""Reuniones por sucursal: sedes con lugar/hora propios y ocurrencias por sede.

sucursal_id = 0 identifica la sesion unica de una reunion sin sedes (evita NULL en la clave unica)."""


def _values(row):
    return list(row.values()) if isinstance(row, dict) else list(row)


def _has_column(cursor, table, column):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND COLUMN_NAME = %s", (table, column))
    return int(_values(cursor.fetchone())[0]) > 0


def _has_index(cursor, table, index):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND INDEX_NAME = %s", (table, index))
    return int(_values(cursor.fetchone())[0]) > 0


def migrate_cursor(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reunion_sedes (
          id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
          reunion_id  INT UNSIGNED NOT NULL,
          sucursal_id INT          NOT NULL,
          lugar       VARCHAR(150) NULL,
          hora_inicio TIME         NULL,
          PRIMARY KEY (id),
          UNIQUE KEY uk_reunion_sedes (reunion_id, sucursal_id),
          CONSTRAINT fk_reunion_sedes_reunion FOREIGN KEY (reunion_id) REFERENCES reuniones (id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    if not _has_column(cursor, "reunion_ocurrencias", "sucursal_id"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD COLUMN sucursal_id INT NOT NULL DEFAULT 0 AFTER reunion_id")
    if not _has_index(cursor, "reunion_ocurrencias", "uk_reunion_ocurrencias_sede_fecha"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD UNIQUE KEY uk_reunion_ocurrencias_sede_fecha"
                       " (reunion_id, sucursal_id, fecha)")
    if _has_index(cursor, "reunion_ocurrencias", "uk_reunion_ocurrencias_fecha"):
        cursor.execute("ALTER TABLE reunion_ocurrencias DROP INDEX uk_reunion_ocurrencias_fecha")
    if not _has_column(cursor, "reunion_asistencias", "sucursal_id"):
        cursor.execute("ALTER TABLE reunion_asistencias ADD COLUMN sucursal_id INT NOT NULL DEFAULT 0 AFTER reunion_id")
    if not _has_index(cursor, "reunion_asistencias", "idx_reunion_asistencias_sede_fecha"):
        cursor.execute("ALTER TABLE reunion_asistencias ADD KEY idx_reunion_asistencias_sede_fecha"
                       " (empresa_id, sucursal_id, fecha)")


if __name__ == "__main__":
    from db import init_orm
    from extensions import get_db
    init_orm()
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(cursor)
        connection.commit()
    finally:
        cursor.close()
        connection.close()
