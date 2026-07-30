import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s LIMIT 1",
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s LIMIT 1",
        (table_name, index_name),
    )
    return cursor.fetchone() is not None


def _constraint_exists(cursor, table_name: str, constraint_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s LIMIT 1",
        (table_name, constraint_name),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _column_exists(cursor, "feedback_motivos", "sector_id"):
            cursor.execute("ALTER TABLE feedback_motivos ADD COLUMN sector_id INT NULL AFTER nombre")
            db.commit()
            print("[created] columna feedback_motivos.sector_id")
        else:
            print("[skip] columna feedback_motivos.sector_id ya existe")

        if not _index_exists(cursor, "feedback_motivos", "idx_feedback_motivos_sector"):
            cursor.execute("ALTER TABLE feedback_motivos ADD INDEX idx_feedback_motivos_sector (sector_id)")
            db.commit()
            print("[created] indice idx_feedback_motivos_sector")
        else:
            print("[skip] indice idx_feedback_motivos_sector ya existe")

        if not _constraint_exists(cursor, "feedback_motivos", "fk_feedback_motivos_sector"):
            cursor.execute(
                "ALTER TABLE feedback_motivos ADD CONSTRAINT fk_feedback_motivos_sector "
                "FOREIGN KEY (sector_id) REFERENCES sectores(id) ON DELETE RESTRICT"
            )
            db.commit()
            print("[created] fk fk_feedback_motivos_sector")
        else:
            print("[skip] fk fk_feedback_motivos_sector ya existe")

        if _index_exists(cursor, "feedback_motivos", "uq_feedback_motivo_nombre"):
            cursor.execute("ALTER TABLE feedback_motivos DROP INDEX uq_feedback_motivo_nombre")
            db.commit()
            print("[dropped] indice unico uq_feedback_motivo_nombre")
        else:
            print("[skip] indice unico uq_feedback_motivo_nombre ya no existe")

        if not _index_exists(cursor, "feedback_motivos", "uq_feedback_motivo_sector_nombre"):
            cursor.execute(
                "ALTER TABLE feedback_motivos ADD UNIQUE KEY uq_feedback_motivo_sector_nombre (sector_id, nombre)"
            )
            db.commit()
            print("[created] indice unico uq_feedback_motivo_sector_nombre")
        else:
            print("[skip] indice unico uq_feedback_motivo_sector_nombre ya existe")

        print("[done] migration 20260721_02_feedback_motivos_sector")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
