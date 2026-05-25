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
        if not _table_exists(cursor, "mobile_sesiones"):
            cursor.execute("""
                CREATE TABLE mobile_sesiones (
                    id                    INT AUTO_INCREMENT PRIMARY KEY,
                    empleado_id           INT NOT NULL,
                    dni                   VARCHAR(20) NOT NULL,
                    ip                    VARCHAR(45) NULL,
                    platform              VARCHAR(10) NULL,
                    device_model          VARCHAR(100) NULL,
                    app_version           VARCHAR(30) NULL,
                    fecha_login           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    fecha_ultimo_request  DATETIME NULL,
                    INDEX idx_ms_empleado  (empleado_id),
                    INDEX idx_ms_fecha     (fecha_login),
                    INDEX idx_ms_platform  (platform),
                    INDEX idx_ms_version   (app_version),
                    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            db.commit()
            print("[created] tabla mobile_sesiones")
        else:
            print("[skip] tabla mobile_sesiones ya existe")

        print("[done] migration 20260524_04_mobile_sesiones")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
