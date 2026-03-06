-- Migration: legajo de empleado multiempresa + eventos de legajo con adjuntos
-- Date: 2026-03-05
-- Notes:
--   - Este archivo describe el esquema objetivo.
--   - Para ejecucion idempotente use scripts/migrate_20260305_01_legajo_multiempresa.py

ALTER TABLE empleados
  DROP INDEX legajo,
  ADD UNIQUE KEY uk_empleados_empresa_legajo (empresa_id, legajo),
  ADD KEY idx_empleados_id_empresa (id, empresa_id);

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
