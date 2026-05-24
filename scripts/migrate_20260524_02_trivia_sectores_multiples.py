import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1
        """,
        (table_name,),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _table_exists(cursor, "trivia_sectores"):
            cursor.execute("""
                CREATE TABLE trivia_sectores (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id  INT NOT NULL,
                    sector_id  INT NOT NULL,
                    UNIQUE KEY uq_ts_trivia_sector (trivia_id, sector_id),
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id) ON DELETE CASCADE,
                    FOREIGN KEY (sector_id) REFERENCES sectores(id) ON DELETE CASCADE,
                    INDEX idx_ts_trivia (trivia_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_sectores")

            # Migrate existing single sector_id values
            cursor.execute("""
                INSERT IGNORE INTO trivia_sectores (trivia_id, sector_id)
                SELECT id, sector_id FROM trivias WHERE sector_id IS NOT NULL
            """)
            migrated = cursor.rowcount
            print(f"[migrated] {migrated} fila(s) de trivias.sector_id → trivia_sectores")
        else:
            print("[skip] tabla trivia_sectores ya existe")

        db.commit()
        print("[done] migration 20260524_02_trivia_sectores_multiples")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
