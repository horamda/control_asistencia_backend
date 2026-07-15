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


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _column_exists(cursor, "skap_preguntas", "puesto_id"):
            cursor.execute(
                "ALTER TABLE skap_preguntas ADD COLUMN puesto_id INT NULL AFTER sector_id"
            )
            db.commit()
            print("[created] columna skap_preguntas.puesto_id")
        else:
            print("[skip] columna skap_preguntas.puesto_id ya existe")

        if not _index_exists(cursor, "skap_preguntas", "idx_skap_preguntas_puesto"):
            cursor.execute(
                "ALTER TABLE skap_preguntas ADD INDEX idx_skap_preguntas_puesto (puesto_id)"
            )
            db.commit()
            print("[created] indice idx_skap_preguntas_puesto")
        else:
            print("[skip] indice idx_skap_preguntas_puesto ya existe")

        if not _index_exists(cursor, "skap_preguntas", "idx_skap_preguntas_sector_puesto_activo"):
            cursor.execute(
                "ALTER TABLE skap_preguntas "
                "ADD INDEX idx_skap_preguntas_sector_puesto_activo (sector_id, puesto_id, activo)"
            )
            db.commit()
            print("[created] indice idx_skap_preguntas_sector_puesto_activo")
        else:
            print("[skip] indice idx_skap_preguntas_sector_puesto_activo ya existe")

        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'skap_preguntas' "
            "AND CONSTRAINT_NAME = 'fk_skap_preguntas_puesto' LIMIT 1"
        )
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE skap_preguntas "
                "ADD CONSTRAINT fk_skap_preguntas_puesto "
                "FOREIGN KEY (puesto_id) REFERENCES puestos(id) ON DELETE CASCADE"
            )
            db.commit()
            print("[created] fk fk_skap_preguntas_puesto")
        else:
            print("[skip] fk fk_skap_preguntas_puesto ya existe")

        if _index_exists(cursor, "skap_preguntas", "uq_skap_preguntas_sector_categoria_desc"):
            cursor.execute(
                "ALTER TABLE skap_preguntas DROP INDEX uq_skap_preguntas_sector_categoria_desc"
            )
            db.commit()
            print("[dropped] indice unico uq_skap_preguntas_sector_categoria_desc")
        else:
            print("[skip] indice unico uq_skap_preguntas_sector_categoria_desc ya no existe")

        if not _index_exists(cursor, "skap_preguntas", "uq_skap_preguntas_sector_puesto_categoria_desc"):
            cursor.execute(
                "ALTER TABLE skap_preguntas "
                "ADD UNIQUE KEY uq_skap_preguntas_sector_puesto_categoria_desc "
                "(sector_id, puesto_id, categoria, descripcion)"
            )
            db.commit()
            print("[created] indice unico uq_skap_preguntas_sector_puesto_categoria_desc")
        else:
            print("[skip] indice unico uq_skap_preguntas_sector_puesto_categoria_desc ya existe")

        print("[done] migration 20260714_01_skap_preguntas_puesto")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
