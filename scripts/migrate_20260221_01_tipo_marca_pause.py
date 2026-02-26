import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL = """
ALTER TABLE asistencia_marcas
  ADD COLUMN IF NOT EXISTS tipo_marca VARCHAR(20) NOT NULL DEFAULT 'jornada' AFTER metodo;

ALTER TABLE qr_puerta_historial
  ADD COLUMN IF NOT EXISTS tipo_marca VARCHAR(20) NOT NULL DEFAULT 'jornada' AFTER sucursal_nombre;
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        for statement in [s.strip() for s in DDL.split(";") if s.strip()]:
            cursor.execute(statement)
        cursor.execute("SHOW INDEX FROM asistencia_marcas")
        existing = {row[2] for row in cursor.fetchall()}
        if "idx_am_tipo_marca_fecha" not in existing:
            cursor.execute(
                "CREATE INDEX idx_am_tipo_marca_fecha ON asistencia_marcas (tipo_marca, fecha)"
            )
        db.commit()
        print("[done] migration 20260221_01_tipo_marca_pause")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
