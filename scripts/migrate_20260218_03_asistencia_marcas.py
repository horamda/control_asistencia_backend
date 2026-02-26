import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL = """
CREATE TABLE IF NOT EXISTS asistencia_marcas (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  asistencia_id INT NULL,
  fecha DATE NOT NULL,
  hora TIME NOT NULL,
  accion ENUM('ingreso','egreso') NOT NULL,
  metodo VARCHAR(20) NOT NULL,
  lat DECIMAL(10,7) NULL,
  lon DECIMAL(10,7) NULL,
  foto TEXT NULL,
  gps_ok TINYINT(1) NULL,
  gps_distancia_m DECIMAL(10,2) NULL,
  gps_tolerancia_m DECIMAL(10,2) NULL,
  gps_ref_lat DECIMAL(10,7) NULL,
  gps_ref_lon DECIMAL(10,7) NULL,
  estado VARCHAR(30) NULL,
  observaciones TEXT NULL,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_am_empleado_fecha_hora (empleado_id, fecha, hora, id),
  INDEX idx_am_empresa_fecha (empresa_id, fecha),
  INDEX idx_am_asistencia (asistencia_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(DDL)
        db.commit()
        print("[done] migration 20260218_03_asistencia_marcas")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
