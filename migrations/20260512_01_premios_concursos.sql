-- Migration: modulo de premios y concursos mensuales
-- Date: 2026-05-12
-- Notes:
--   - premios_concursos define los concursos disponibles por empresa.
--   - premios_resultados guarda el ranking mensual obtenido por empleado.
--   - El concurso SEGURIDAD debe crearse con alcance = 'global' y sector_id = NULL.

CREATE TABLE IF NOT EXISTS premios_concursos (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  sector_id INT NULL,
  codigo VARCHAR(64) NOT NULL,
  nombre VARCHAR(120) NOT NULL,
  descripcion VARCHAR(255) NULL,
  alcance ENUM('sector', 'global') NOT NULL DEFAULT 'sector',
  activo TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_premios_concursos_empresa_codigo (empresa_id, codigo),
  KEY idx_premios_concursos_empresa_activo (empresa_id, activo),
  KEY idx_premios_concursos_sector_activo (sector_id, activo),
  CONSTRAINT fk_premios_concursos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_premios_concursos_sector FOREIGN KEY (sector_id) REFERENCES sectores (id),
  CONSTRAINT chk_premios_concursos_alcance_sector CHECK (
    (alcance = 'global' AND sector_id IS NULL)
    OR
    (alcance = 'sector' AND sector_id IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS premios_resultados (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  concurso_id INT UNSIGNED NOT NULL,
  sector_id INT NULL,
  periodo DATE NOT NULL,
  ranking SMALLINT UNSIGNED NOT NULL,
  legajo_snapshot VARCHAR(50) NOT NULL,
  empleado_nombre_snapshot VARCHAR(150) NOT NULL,
  concurso_codigo_snapshot VARCHAR(64) NOT NULL,
  concurso_nombre_snapshot VARCHAR(120) NOT NULL,
  observaciones VARCHAR(255) NULL,
  created_by_usuario_id INT NULL,
  updated_by_usuario_id INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_premios_resultados_empleado_concurso_periodo (empleado_id, concurso_id, periodo),
  UNIQUE KEY uk_premios_resultados_concurso_periodo_ranking (concurso_id, periodo, ranking),
  KEY idx_premios_resultados_empresa_periodo (empresa_id, periodo),
  KEY idx_premios_resultados_empleado_periodo (empleado_id, periodo),
  KEY idx_premios_resultados_sector_periodo (sector_id, periodo),
  KEY idx_premios_resultados_ranking (ranking),
  CONSTRAINT fk_premios_resultados_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_premios_resultados_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id),
  CONSTRAINT fk_premios_resultados_concurso FOREIGN KEY (concurso_id) REFERENCES premios_concursos (id),
  CONSTRAINT fk_premios_resultados_sector FOREIGN KEY (sector_id) REFERENCES sectores (id),
  CONSTRAINT fk_premios_resultados_created_by FOREIGN KEY (created_by_usuario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_premios_resultados_updated_by FOREIGN KEY (updated_by_usuario_id) REFERENCES usuarios (id),
  CONSTRAINT chk_premios_resultados_ranking CHECK (ranking >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT IGNORE INTO premios_concursos
  (empresa_id, sector_id, codigo, nombre, descripcion, alcance, activo)
SELECT
  e.id,
  NULL,
  'SEGURIDAD',
  'Premio de seguridad',
  'Concurso global disponible para empleados de cualquier sector.',
  'global',
  1
FROM empresas e;
