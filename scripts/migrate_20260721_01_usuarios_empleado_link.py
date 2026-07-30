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
        if not _column_exists(cursor, "usuarios", "empleado_id"):
            cursor.execute("ALTER TABLE usuarios ADD COLUMN empleado_id INT NULL AFTER empresa_id")
            db.commit()
            print("[created] columna usuarios.empleado_id")
        else:
            print("[skip] columna usuarios.empleado_id ya existe")

        if not _index_exists(cursor, "usuarios", "idx_usuarios_empleado"):
            cursor.execute("ALTER TABLE usuarios ADD INDEX idx_usuarios_empleado (empleado_id)")
            db.commit()
            print("[created] indice idx_usuarios_empleado")
        else:
            print("[skip] indice idx_usuarios_empleado ya existe")

        if not _constraint_exists(cursor, "usuarios", "fk_usuarios_empleado"):
            cursor.execute(
                "ALTER TABLE usuarios ADD CONSTRAINT fk_usuarios_empleado "
                "FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE SET NULL"
            )
            db.commit()
            print("[created] fk fk_usuarios_empleado")
        else:
            print("[skip] fk fk_usuarios_empleado ya existe")

        print("[done] migration 20260721_01_usuarios_empleado_link")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
