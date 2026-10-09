"""Additive EPP schema; no employee or historical data is modified."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def migrate_cursor(cursor):
    for sql in (
        (ROOT / "migrations/20261008_02_epp.sql").read_text(encoding="utf-8").split(";")
    ):
        if sql.strip():
            cursor.execute(sql)


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
        print(
            "EPP: ocho tablas instaladas. Configure articulos y responsables desde el panel."
        )
    finally:
        cursor.close()
        connection.close()
