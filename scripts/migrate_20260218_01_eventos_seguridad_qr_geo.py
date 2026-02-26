import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL = """
CREATE TABLE IF NOT EXISTS eventos_seguridad (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT NOT NULL,
  empresa_id INT NOT NULL,
  tipo_evento VARCHAR(50) NOT NULL,
  severidad VARCHAR(20) NOT NULL DEFAULT 'alta',
  fecha_operacion DATE NULL,
  hora_operacion TIME NULL,
  lat DECIMAL(10,7) NULL,
  lon DECIMAL(10,7) NULL,
  ref_lat DECIMAL(10,7) NULL,
  ref_lon DECIMAL(10,7) NULL,
  distancia_m DECIMAL(10,2) NULL,
  tolerancia_m DECIMAL(10,2) NULL,
  sucursal_id INT NULL,
  qr_accion VARCHAR(20) NULL,
  qr_scope VARCHAR(20) NULL,
  qr_empresa_id INT NULL,
  alerta_fraude TINYINT(1) NOT NULL DEFAULT 1,
  payload_json JSON NULL,
  fecha DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_eventos_seguridad_empleado_fecha (empleado_id, fecha),
  INDEX idx_eventos_seguridad_empresa_fecha (empresa_id, fecha),
  INDEX idx_eventos_seguridad_tipo_fecha (tipo_evento, fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(DDL)
        db.commit()
        print("[done] migration 20260218_01_eventos_seguridad_qr_geo")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
