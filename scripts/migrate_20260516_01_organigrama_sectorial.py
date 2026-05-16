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


def _constraint_exists(cursor, table_name: str, constraint_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = %s
        LIMIT 1
        """,
        (table_name, constraint_name),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _column_exists(cursor, "sectores", "sector_padre_id"):
            cursor.execute(
                "ALTER TABLE sectores ADD COLUMN sector_padre_id INT NULL AFTER empresa_id"
            )
        if not _column_exists(cursor, "sectores", "responsable_empleado_id"):
            cursor.execute(
                "ALTER TABLE sectores ADD COLUMN responsable_empleado_id INT NULL AFTER sector_padre_id"
            )
        if not _index_exists(cursor, "sectores", "idx_sectores_sector_padre"):
            cursor.execute(
                "ALTER TABLE sectores ADD INDEX idx_sectores_sector_padre (sector_padre_id)"
            )
        if not _index_exists(cursor, "sectores", "idx_sectores_responsable"):
            cursor.execute(
                "ALTER TABLE sectores ADD INDEX idx_sectores_responsable (responsable_empleado_id)"
            )
        if not _constraint_exists(cursor, "sectores", "fk_sectores_sector_padre"):
            cursor.execute(
                """
                ALTER TABLE sectores
                ADD CONSTRAINT fk_sectores_sector_padre
                FOREIGN KEY (sector_padre_id) REFERENCES sectores (id)
                ON DELETE SET NULL
                """
            )
        if not _constraint_exists(cursor, "sectores", "fk_sectores_responsable"):
            cursor.execute(
                """
                ALTER TABLE sectores
                ADD CONSTRAINT fk_sectores_responsable
                FOREIGN KEY (responsable_empleado_id) REFERENCES empleados (id)
                ON DELETE SET NULL
                """
            )
        db.commit()
        print("[done] migration 20260516_01_organigrama_sectorial")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
