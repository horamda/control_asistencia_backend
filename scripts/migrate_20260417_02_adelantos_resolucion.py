import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _column_exists(cursor, table_name: str, column_name: str):
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


def _index_exists(cursor, table_name: str, index_name: str):
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
    cursor = db.cursor()
    try:
        if not _column_exists(cursor, "adelantos", "resuelto_by_usuario_id"):
            cursor.execute("ALTER TABLE adelantos ADD COLUMN resuelto_by_usuario_id INT NULL AFTER estado")
            print("[ok] added adelantos.resuelto_by_usuario_id")
        else:
            print("[skip] adelantos.resuelto_by_usuario_id already exists")

        if not _column_exists(cursor, "adelantos", "resuelto_at"):
            cursor.execute("ALTER TABLE adelantos ADD COLUMN resuelto_at DATETIME NULL AFTER resuelto_by_usuario_id")
            print("[ok] added adelantos.resuelto_at")
        else:
            print("[skip] adelantos.resuelto_at already exists")

        if not _index_exists(cursor, "adelantos", "idx_adelantos_resuelto_by"):
            cursor.execute(
                "ALTER TABLE adelantos ADD INDEX idx_adelantos_resuelto_by (resuelto_by_usuario_id)"
            )
            print("[ok] added idx_adelantos_resuelto_by")
        else:
            print("[skip] idx_adelantos_resuelto_by already exists")

        db.commit()
        print("[done] migration 20260417_02_adelantos_resolucion")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
