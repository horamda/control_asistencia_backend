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
        if not _table_exists(cursor, "trivia_exclusiones"):
            cursor.execute("""
                CREATE TABLE trivia_exclusiones (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id   INT NOT NULL,
                    empleado_id INT NOT NULL,
                    motivo      VARCHAR(300) NULL,
                    creado_por  INT NULL,
                    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_te_trivia_empleado (trivia_id, empleado_id),
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id) ON DELETE CASCADE,
                    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE,
                    INDEX idx_te_trivia (trivia_id),
                    INDEX idx_te_empleado (empleado_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            db.commit()
            print("[created] tabla trivia_exclusiones")
        else:
            print("[skip] tabla trivia_exclusiones ya existe")

        print("[done] migration 20260527_01_trivia_exclusiones")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
