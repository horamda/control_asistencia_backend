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


def _add_column(cursor, name: str, definition: str) -> bool:
    if _column_exists(cursor, "feedbacks", name):
        print(f"[skip] feedbacks.{name} ya existe")
        return False
    cursor.execute(f"ALTER TABLE feedbacks ADD COLUMN {name} {definition}")
    print(f"[add] feedbacks.{name}")
    return True


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        changed = False
        changed |= _add_column(cursor, "evidencia_filename", "VARCHAR(255) NULL AFTER resolucion_descripcion")
        changed |= _add_column(cursor, "evidencia_path", "VARCHAR(500) NULL AFTER evidencia_filename")
        changed |= _add_column(cursor, "evidencia_mime_type", "VARCHAR(100) NULL AFTER evidencia_path")
        changed |= _add_column(cursor, "evidencia_size_bytes", "INT NULL AFTER evidencia_mime_type")
        if changed:
            db.commit()
        print("[done] migration 20260722_01_feedback_evidencia")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
