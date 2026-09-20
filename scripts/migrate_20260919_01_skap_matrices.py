"""Additive, repeatable migration; does not run the application's other migrations."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions import get_db
from db import init_orm


def migrate():
    init_orm()
    db = get_db()
    cursor = db.cursor()
    try:
        sql = (ROOT / 'migrations/20260919_01_skap_matrices.sql').read_text(encoding='utf-8')
        sql = '\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
        for statement in sql.split(';'):
            if statement.strip():
                cursor.execute(statement)
        db.commit()
    finally:
        cursor.close()
        db.close()
    print('Migración SKAP operativa aplicada.')


if __name__ == '__main__':
    migrate()
