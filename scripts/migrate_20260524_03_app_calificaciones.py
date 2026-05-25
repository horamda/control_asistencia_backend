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
        if not _table_exists(cursor, "app_calificaciones"):
            cursor.execute("""
                CREATE TABLE app_calificaciones (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    empleado_id   INT NOT NULL,
                    dni           VARCHAR(20) NOT NULL,
                    puntuacion    TINYINT NOT NULL,
                    comentario    TEXT NULL,
                    pantalla      VARCHAR(100) NULL,
                    version_app   VARCHAR(30) NULL,
                    fecha         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_empleado_version (empleado_id, version_app),
                    INDEX idx_cal_fecha      (fecha),
                    INDEX idx_cal_version    (version_app),
                    INDEX idx_cal_puntuacion (puntuacion),
                    INDEX idx_cal_empleado   (empleado_id),
                    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            db.commit()
            print("[created] tabla app_calificaciones")
        else:
            print("[skip] tabla app_calificaciones ya existe")

        print("[done] migration 20260524_03_app_calificaciones")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
