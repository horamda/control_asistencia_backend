"""Vista del Historial de marcas (asistencia_marcas_reporte) en el bootstrap, para una base armada desde cero.

La vista, la columna asistencia_marcas.corregida_manualmente y la tabla asistencia_correcciones se crearon con un script
aparte (migrate_20260920_03_asistencia_reportes.py) que el deploy no corre. Aca solo se crea lo que falta: en una base
que ya los tiene (produccion) no cambia nada; en particular, una vista existente nunca se reemplaza.

Reversion: borrar la version 20261020_vista_reporte_marcas de app_schema_versions (no hace falta tocar la vista)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISTA = ROOT / "migrations/20260920_03_asistencia_reportes.sql"

CORRECCIONES = """
CREATE TABLE IF NOT EXISTS asistencia_correcciones (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, asistencia_id INT NOT NULL,
  usuario_id INT NULL, accion VARCHAR(30) NOT NULL,
  antes LONGTEXT NULL, despues LONGTEXT NULL,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ac_asistencia (asistencia_id, creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _existe(cursor, sql, args):
    cursor.execute(sql, args)
    return bool(cursor.fetchone()[0])


def migrate_cursor(cursor):
    if not _existe(cursor, """SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
                              AND TABLE_NAME = 'asistencia_marcas' AND COLUMN_NAME = %s""", ("corregida_manualmente",)):
        cursor.execute("ALTER TABLE asistencia_marcas ADD COLUMN corregida_manualmente TINYINT(1) NOT NULL DEFAULT 0")
    cursor.execute(CORRECCIONES)
    if not _existe(cursor, """SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()
                              AND TABLE_NAME = %s""", ("asistencia_marcas_reporte",)):
        cursor.execute(VISTA.read_text(encoding="utf-8").strip().rstrip(";"))


if __name__ == "__main__":
    from db import init_orm
    from extensions import get_db
    init_orm()
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(cursor)
        connection.commit()
    finally:
        cursor.close()
        connection.close()
