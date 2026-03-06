import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL_TIPOS = """
CREATE TABLE IF NOT EXISTS legajo_tipos_evento (
  id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo VARCHAR(40) NOT NULL,
  nombre VARCHAR(80) NOT NULL,
  requiere_rango_fechas TINYINT(1) NOT NULL DEFAULT 0,
  permite_adjuntos TINYINT(1) NOT NULL DEFAULT 1,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_legajo_tipos_evento_codigo (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""


DDL_EVENTOS = """
CREATE TABLE IF NOT EXISTS legajo_eventos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  tipo_id SMALLINT UNSIGNED NOT NULL,
  fecha_evento DATE NOT NULL,
  fecha_desde DATE NULL,
  fecha_hasta DATE NULL,
  titulo VARCHAR(150) NULL,
  descripcion TEXT NOT NULL,
  estado ENUM('vigente', 'anulado') NOT NULL DEFAULT 'vigente',
  severidad ENUM('leve', 'media', 'grave') NULL,
  justificacion_id INT NULL,
  created_by_usuario_id INT NULL,
  updated_by_usuario_id INT NULL,
  anulado_by_usuario_id INT NULL,
  anulado_motivo VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  anulado_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_legajo_eventos_emp_fecha (empleado_id, fecha_evento, id),
  KEY idx_legajo_eventos_empresa_tipo_fecha (empresa_id, tipo_id, fecha_evento),
  KEY idx_legajo_eventos_estado (estado),
  CONSTRAINT fk_legajo_eventos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_legajo_eventos_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id),
  CONSTRAINT fk_legajo_eventos_tipo FOREIGN KEY (tipo_id) REFERENCES legajo_tipos_evento (id),
  CONSTRAINT fk_legajo_eventos_justificacion FOREIGN KEY (justificacion_id) REFERENCES justificaciones (id),
  CONSTRAINT fk_legajo_eventos_created_by FOREIGN KEY (created_by_usuario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_legajo_eventos_updated_by FOREIGN KEY (updated_by_usuario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_legajo_eventos_anulado_by FOREIGN KEY (anulado_by_usuario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""


DDL_ADJUNTOS = """
CREATE TABLE IF NOT EXISTS legajo_evento_adjuntos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  evento_id BIGINT UNSIGNED NOT NULL,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  nombre_original VARCHAR(255) NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  extension VARCHAR(16) NULL,
  tamano_bytes INT UNSIGNED NOT NULL,
  sha256 CHAR(64) NOT NULL,
  storage_backend ENUM('local', 'ftp', 'db') NOT NULL DEFAULT 'local',
  storage_ruta VARCHAR(500) NOT NULL,
  estado ENUM('activo', 'eliminado') NOT NULL DEFAULT 'activo',
  created_by_usuario_id INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_by_usuario_id INT NULL,
  deleted_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_legajo_adjuntos_evento_sha256 (evento_id, sha256),
  KEY idx_legajo_adjuntos_evento (evento_id),
  KEY idx_legajo_adjuntos_emp_fecha (empleado_id, created_at),
  KEY idx_legajo_adjuntos_estado (estado),
  CONSTRAINT fk_legajo_adjuntos_evento FOREIGN KEY (evento_id) REFERENCES legajo_eventos (id) ON DELETE CASCADE,
  CONSTRAINT fk_legajo_adjuntos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_legajo_adjuntos_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id),
  CONSTRAINT fk_legajo_adjuntos_created_by FOREIGN KEY (created_by_usuario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_legajo_adjuntos_deleted_by FOREIGN KEY (deleted_by_usuario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""


SEED_TIPOS = """
INSERT IGNORE INTO legajo_tipos_evento (
  codigo,
  nombre,
  requiere_rango_fechas,
  permite_adjuntos,
  activo
) VALUES
  ('certificado_medico', 'Certificado medico', 0, 1, 1),
  ('amonestacion', 'Amonestacion', 0, 1, 1),
  ('suspension', 'Suspension', 1, 1, 1),
  ('nota', 'Nota interna', 0, 1, 1),
  ('otro', 'Otro', 0, 1, 1);
"""


def _load_indexes(cursor, table_name: str):
    cursor.execute(f"SHOW INDEX FROM {table_name}")
    rows = cursor.fetchall()
    indexes = {}
    for row in rows:
        name = row["Key_name"]
        info = indexes.setdefault(
            name,
            {
                "non_unique": int(row["Non_unique"]),
                "columns": [],
            },
        )
        info["columns"].append((int(row["Seq_in_index"]), row["Column_name"]))
    for info in indexes.values():
        info["columns"] = [column for _, column in sorted(info["columns"], key=lambda item: item[0])]
    return indexes


def _find_index_name(indexes: dict, columns: list[str], unique: bool | None = None):
    expected = list(columns)
    for name, info in indexes.items():
        if info["columns"] != expected:
            continue
        if unique is None:
            return name
        is_unique = info["non_unique"] == 0
        if is_unique == unique:
            return name
    return None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        indexes = _load_indexes(cursor, "empleados")
        old_legajo_unique = _find_index_name(indexes, ["legajo"], unique=True)
        if old_legajo_unique:
            cursor.execute(f"ALTER TABLE empleados DROP INDEX {old_legajo_unique}")

        indexes = _load_indexes(cursor, "empleados")
        empresa_legajo_unique = _find_index_name(indexes, ["empresa_id", "legajo"], unique=True)
        if not empresa_legajo_unique:
            cursor.execute(
                "ALTER TABLE empleados "
                "ADD UNIQUE INDEX uk_empleados_empresa_legajo (empresa_id, legajo)"
            )

        indexes = _load_indexes(cursor, "empleados")
        id_empresa_idx = _find_index_name(indexes, ["id", "empresa_id"], unique=None)
        if not id_empresa_idx:
            cursor.execute(
                "ALTER TABLE empleados "
                "ADD INDEX idx_empleados_id_empresa (id, empresa_id)"
            )

        cursor.execute(DDL_TIPOS)
        cursor.execute(DDL_EVENTOS)
        cursor.execute(DDL_ADJUNTOS)
        cursor.execute(SEED_TIPOS)

        db.commit()
        print("[done] migration 20260305_01_legajo_multiempresa")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
