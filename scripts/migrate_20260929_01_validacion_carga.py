"""Migracion aditiva e idempotente. No modifica otros modulos ni asigna permisos."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import init_orm
from extensions import get_db


def migrate():
    init_orm()
    db = get_db()
    cursor = db.cursor()
    try:
        sql = (ROOT / 'migrations/20260929_01_validacion_carga.sql').read_text(encoding='utf-8')
        sql = '\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
        for statement in sql.split(';'):
            if statement.strip():
                cursor.execute(statement)
        db.commit()
    finally:
        cursor.close()
        db.close()
    print('Migracion de validacion de carga aplicada. Configure puestos, camiones y horarios en el panel.')


if __name__ == '__main__':
    migrate()
