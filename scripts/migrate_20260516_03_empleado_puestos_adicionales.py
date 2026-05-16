import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL_EMPLEADO_PUESTOS = """
CREATE TABLE IF NOT EXISTS empleado_puestos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT NOT NULL,
  empresa_id INT NOT NULL,
  sector_id INT NOT NULL,
  puesto_id INT NOT NULL,
  activo TINYINT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_empleado_puestos_unico (empleado_id, sector_id, puesto_id),
  KEY idx_empleado_puestos_empleado_activo (empleado_id, activo),
  KEY idx_empleado_puestos_sector_activo (sector_id, activo),
  KEY idx_empleado_puestos_puesto (puesto_id),
  CONSTRAINT fk_empleado_puestos_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id) ON DELETE CASCADE,
  CONSTRAINT fk_empleado_puestos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_empleado_puestos_sector FOREIGN KEY (sector_id) REFERENCES sectores (id),
  CONSTRAINT fk_empleado_puestos_puesto FOREIGN KEY (puesto_id) REFERENCES puestos (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(DDL_EMPLEADO_PUESTOS)
        db.commit()
        print("[done] migration 20260516_03_empleado_puestos_adicionales")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
