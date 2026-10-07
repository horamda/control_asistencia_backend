"""Migración aditiva e idempotente: no clasifica respuestas ni crea personas."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import init_orm
from extensions import get_db


def migrate():
    init_orm()
    connection=get_db()
    cursor=connection.cursor()
    try:
        for sql in (ROOT/'migrations/20261005_01_seguridad_externos.sql').read_text(encoding='utf-8').split(';'):
            if sql.strip(): cursor.execute(sql)
        connection.commit()
    finally:
        cursor.close(); connection.close()
    print('Seguridad e Higiene: soporte de personas externas instalado.')


if __name__=='__main__':
    migrate()
