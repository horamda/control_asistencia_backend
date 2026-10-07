"""Install editable safety champion rules and immutable award snapshots."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from db import init_orm
from extensions import get_db

def migrate():
    init_orm()
    connection=get_db();cursor=connection.cursor()
    try:
        cursor.execute('SET SESSION lock_wait_timeout=5')
        for statement in (ROOT/'migrations/20261007_01_seguridad_campeon.sql').read_text(encoding='utf-8').split(';'):
            if statement.strip():cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close();connection.close()
    print('Reglas y reconocimientos de Seguridad e Higiene instalados.')

if __name__=='__main__':migrate()
