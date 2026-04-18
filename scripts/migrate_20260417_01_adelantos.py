import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL_ADELANTOS = """
CREATE TABLE IF NOT EXISTS adelantos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  periodo_year SMALLINT NOT NULL,
  periodo_month TINYINT UNSIGNED NOT NULL,
  fecha_solicitud DATE NOT NULL,
  estado ENUM('pendiente', 'aprobado', 'rechazado', 'cancelado') NOT NULL DEFAULT 'pendiente',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_adelantos_empleado_periodo (empleado_id, periodo_year, periodo_month),
  KEY idx_adelantos_empresa_periodo (empresa_id, periodo_year, periodo_month),
  KEY idx_adelantos_estado (estado),
  CONSTRAINT fk_adelantos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_adelantos_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(DDL_ADELANTOS)
        db.commit()
        print("[done] migration 20260417_01_adelantos")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
