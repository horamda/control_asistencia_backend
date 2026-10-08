"""Create reimbursement tables; does not approve or pay expenses."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import init_orm
from extensions import get_db


def migrate():
    init_orm()
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SET SESSION lock_wait_timeout=5")
        for sql in (
            (ROOT / "migrations/20261007_02_reintegros.sql")
            .read_text(encoding="utf-8")
            .split(";")
        ):
            if sql.strip():
                c.execute(sql)
        conn.commit()
    finally:
        c.close()
        conn.close()
    print("Modulo de reintegros instalado.")


if __name__ == "__main__":
    migrate()
