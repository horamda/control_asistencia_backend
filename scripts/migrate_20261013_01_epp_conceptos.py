"""Add replacement concepts without changing existing orders."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def migrate_cursor(cursor):
    for sql in (ROOT / "migrations/20261013_01_epp_conceptos.sql").read_text(encoding="utf-8").split(";"):
        if sql.strip():
            cursor.execute(sql)
    for name, definition in [("concepto_reposicion_id", "INT NULL"), ("concepto_reposicion", "VARCHAR(120) NULL")]:
        cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='epp_pedidos' AND COLUMN_NAME=%s", (name,))
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE epp_pedidos ADD COLUMN {name} {definition}")

if __name__ == "__main__":
    from db import init_orm
    from extensions import get_db
    init_orm()
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(cursor)
        connection.commit()
        print("Conceptos de reposición EPP instalados.")
    finally:
        cursor.close()
        connection.close()
