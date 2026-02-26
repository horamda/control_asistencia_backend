import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL = """
ALTER TABLE configuracion_empresa
  ADD COLUMN IF NOT EXISTS cooldown_scan_segundos INT NULL AFTER tolerancia_global;
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        for statement in [s.strip() for s in DDL.split(";") if s.strip()]:
            cursor.execute(statement)
        db.commit()
        print("[done] migration 20260225_01_configuracion_empresa_scan_cooldown")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
