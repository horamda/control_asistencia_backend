"""Add per-trivia ranking exclusions; preserves existing participation exclusions."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import init_orm
from extensions import get_db


def migrate():
    init_orm()
    db = get_db()
    c = db.cursor()
    try:
        sql = (ROOT / 'migrations/20260920_02_trivia_ranking_exclusiones.sql').read_text(encoding='utf-8-sig')
        c.execute(sql.strip().rstrip(';'))
        db.commit()
    finally:
        c.close(); db.close()
    print('Migracion de participaciones fuera de ranking aplicada.')

if __name__ == '__main__':
    migrate()
