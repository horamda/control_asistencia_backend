import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


COLUMNS = [
    ("gps_ok_entrada", "TINYINT(1) NULL"),
    ("gps_distancia_entrada_m", "DECIMAL(10,2) NULL"),
    ("gps_tolerancia_entrada_m", "DECIMAL(10,2) NULL"),
    ("gps_ref_lat_entrada", "DECIMAL(10,7) NULL"),
    ("gps_ref_lon_entrada", "DECIMAL(10,7) NULL"),
    ("gps_ok_salida", "TINYINT(1) NULL"),
    ("gps_distancia_salida_m", "DECIMAL(10,2) NULL"),
    ("gps_tolerancia_salida_m", "DECIMAL(10,2) NULL"),
    ("gps_ref_lat_salida", "DECIMAL(10,7) NULL"),
    ("gps_ref_lon_salida", "DECIMAL(10,7) NULL"),
]


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


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        for column_name, column_def in COLUMNS:
            if _column_exists(cursor, "asistencias", column_name):
                print(f"[skip] asistencias.{column_name} already exists")
                continue
            sql = f"ALTER TABLE asistencias ADD COLUMN {column_name} {column_def}"
            cursor.execute(sql)
            print(f"[ok] added asistencias.{column_name}")
        db.commit()
        print("[done] migration 20260216_01_asistencias_gps_columns")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
