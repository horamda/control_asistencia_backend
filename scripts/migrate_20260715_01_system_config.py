import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
        (table_name,),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _table_exists(cursor, "system_config"):
            cursor.execute(
                """
                CREATE TABLE system_config (
                    config_key   VARCHAR(100) NOT NULL,
                    config_value VARCHAR(255) NOT NULL,
                    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (config_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            db.commit()
            print("[created] tabla system_config")
        else:
            print("[skip] tabla system_config ya existe")
        print("[done] migration 20260715_01_system_config")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
