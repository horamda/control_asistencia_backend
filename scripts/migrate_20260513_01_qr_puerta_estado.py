import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


COLUMNS = {
    "qr_token_hash": "CHAR(64) NULL AFTER qr_token",
    "activo": "TINYINT NOT NULL DEFAULT 1 AFTER usuario_id",
    "inactivado_at": "DATETIME NULL AFTER activo",
    "inactivado_by_usuario": "INT NULL AFTER inactivado_at",
    "inactivado_motivo": "VARCHAR(255) NULL AFTER inactivado_by_usuario",
}

INDEXES = {
    "idx_qr_puerta_historial_token_hash": "(qr_token_hash)",
    "idx_qr_puerta_historial_activo_fecha": "(activo, fecha)",
}


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM qr_puerta_historial")
        existing_columns = {row[0] for row in cursor.fetchall()}
        for name, ddl in COLUMNS.items():
            if name not in existing_columns:
                cursor.execute(f"ALTER TABLE qr_puerta_historial ADD COLUMN {name} {ddl}")

        cursor.execute(
            """
            UPDATE qr_puerta_historial
            SET qr_token_hash = SHA2(qr_token, 256)
            WHERE id > 0
              AND (qr_token_hash IS NULL OR qr_token_hash = '')
            """
        )

        cursor.execute("SHOW INDEX FROM qr_puerta_historial")
        existing_indexes = {row[2] for row in cursor.fetchall()}
        for name, columns in INDEXES.items():
            if name not in existing_indexes:
                cursor.execute(f"CREATE INDEX {name} ON qr_puerta_historial {columns}")

        db.commit()
        print("[done] migration 20260513_01_qr_puerta_estado")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
