import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL = """
SET @schema_name = DATABASE();

SET @column_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'configuracion_empresa'
    AND COLUMN_NAME = 'cooldown_scan_segundos'
);

SET @sql := IF(
  @column_exists = 0,
  'ALTER TABLE configuracion_empresa ADD COLUMN cooldown_scan_segundos INT NULL AFTER tolerancia_global',
  'SELECT ''skip configuracion_empresa.cooldown_scan_segundos'' AS info'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
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
