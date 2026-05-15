import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL_VACACIONES_MOVIMIENTOS = """
CREATE TABLE IF NOT EXISTS vacaciones_movimientos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT NOT NULL,
  empresa_id INT NOT NULL,
  anio SMALLINT NOT NULL,
  tipo ENUM('tomado', 'compensatorio', 'ajuste') NOT NULL,
  dias DECIMAL(5,2) NOT NULL,
  observacion VARCHAR(255) NULL,
  fecha_desde DATE NULL,
  fecha_hasta DATE NULL,
  estado ENUM('pendiente', 'aprobado', 'rechazado') NOT NULL DEFAULT 'aprobado',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_vac_mov_empleado_anio (empleado_id, anio),
  KEY idx_vac_mov_empresa_anio_estado (empresa_id, anio, estado),
  KEY idx_vac_mov_tipo_estado (tipo, estado),
  CONSTRAINT fk_vac_mov_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_vac_mov_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id),
  CONSTRAINT chk_vac_mov_dias_no_cero CHECK (dias <> 0),
  CONSTRAINT chk_vac_mov_tomado_fechas CHECK (
    tipo <> 'tomado'
    OR (
      fecha_desde IS NOT NULL
      AND fecha_hasta IS NOT NULL
      AND fecha_desde <= fecha_hasta
    )
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
"""


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _column_exists(cursor, "empleados", "fecha_ingreso"):
            cursor.execute(
                "ALTER TABLE empleados ADD COLUMN fecha_ingreso DATE NULL AFTER fecha_nacimiento"
            )
        cursor.execute(DDL_VACACIONES_MOVIMIENTOS)
        db.commit()
        print("[done] migration 20260515_01_vacaciones_movimientos")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
