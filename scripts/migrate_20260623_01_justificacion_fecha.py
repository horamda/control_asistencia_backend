import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table_name, index_name),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if not _column_exists(cursor, "justificaciones", "fecha"):
            cursor.execute(
                "ALTER TABLE justificaciones "
                "ADD COLUMN fecha DATE NULL AFTER asistencia_id"
            )

        cursor.execute("SET @old_safe_updates := @@SQL_SAFE_UPDATES")
        cursor.execute("SET SQL_SAFE_UPDATES = 0")
        try:
            cursor.execute(
                """
                UPDATE justificaciones j
                LEFT JOIN asistencias a ON a.id = j.asistencia_id
                SET j.fecha = COALESCE(j.fecha, a.fecha, DATE(j.created_at))
                WHERE j.fecha IS NULL
                """
            )
        finally:
            cursor.execute("SET SQL_SAFE_UPDATES = @old_safe_updates")

        cursor.execute(
            """
            SELECT IS_NULLABLE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'justificaciones'
              AND COLUMN_NAME = 'fecha'
            """
        )
        row = cursor.fetchone() or {}
        if str(row.get("IS_NULLABLE") or "").upper() == "YES":
            cursor.execute("ALTER TABLE justificaciones MODIFY fecha DATE NOT NULL")

        if not _index_exists(cursor, "justificaciones", "idx_justificaciones_empleado_fecha"):
            cursor.execute(
                "ALTER TABLE justificaciones "
                "ADD INDEX idx_justificaciones_empleado_fecha (empleado_id, fecha, estado)"
            )

        db.commit()
        print("[done] migration 20260623_01_justificacion_fecha")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
