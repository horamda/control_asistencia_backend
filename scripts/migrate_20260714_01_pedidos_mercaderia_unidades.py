import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM pedidos_mercaderia_items")
        existing_columns = {row[0] for row in cursor.fetchall()}
        if "cantidad_unidades" not in existing_columns:
            cursor.execute(
                "ALTER TABLE pedidos_mercaderia_items "
                "ADD COLUMN cantidad_unidades INT UNSIGNED NOT NULL DEFAULT 0 "
                "AFTER cantidad_bultos"
            )
        db.commit()
        print("[done] migration 20260714_01_pedidos_mercaderia_unidades")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
