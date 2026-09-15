import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        LIMIT 1
        """,
        (table_name,),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if _table_exists(cursor, "usuario_modulo_permisos"):
            print("[skip] tabla usuario_modulo_permisos ya existe")
        else:
            cursor.execute(
                """
                CREATE TABLE usuario_modulo_permisos (
                    id              INT NOT NULL AUTO_INCREMENT,
                    usuario_id      INT NOT NULL,
                    modulo          VARCHAR(80) NOT NULL,
                    puede_ver       TINYINT(1) NOT NULL DEFAULT 0,
                    puede_crear     TINYINT(1) NOT NULL DEFAULT 0,
                    puede_editar    TINYINT(1) NOT NULL DEFAULT 0,
                    puede_eliminar  TINYINT(1) NOT NULL DEFAULT 0,
                    puede_aprobar   TINYINT(1) NOT NULL DEFAULT 0,
                    puede_exportar  TINYINT(1) NOT NULL DEFAULT 0,
                    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_usuario_modulo_permiso (usuario_id, modulo),
                    KEY idx_usuario_modulo_permiso_modulo (modulo),
                    CONSTRAINT fk_usuario_modulo_permisos_usuario
                        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            db.commit()
            print("[created] tabla usuario_modulo_permisos")
        print("[done] migration 20260818_01_usuario_modulo_permisos")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
