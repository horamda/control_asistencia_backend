"""Add the safety dashboard's coverage setting without assuming a start date."""
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
        for statement in (ROOT/'migrations/20261005_02_seguridad_dashboard.sql').read_text(encoding='utf-8').split(';'):
            if statement.strip(): cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close();connection.close()
    print('Configuracion del dashboard de Seguridad e Higiene instalada.')

if __name__=='__main__': migrate()
