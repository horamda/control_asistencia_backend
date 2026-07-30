-- Migracion: permisos mobile para cargar eventos de legajo y tipos habilitados para mobile.
-- Compatible con MySQL sin ADD COLUMN IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS empleado_mobile_permisos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT NOT NULL,
  permiso VARCHAR(80) NOT NULL,
  alcance VARCHAR(30) NOT NULL DEFAULT 'sector',
  activo TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_emp_mobile_permiso (empleado_id, permiso),
  KEY idx_emp_mobile_permiso_activo (permiso, activo),
  CONSTRAINT fk_emp_mobile_permisos_empleado
    FOREIGN KEY (empleado_id) REFERENCES empleados (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @col_habilitado_mobile := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'legajo_tipos_evento'
    AND COLUMN_NAME = 'habilitado_mobile'
);

SET @sql_habilitado_mobile := IF(
  @col_habilitado_mobile = 0,
  'ALTER TABLE legajo_tipos_evento ADD COLUMN habilitado_mobile TINYINT(1) NOT NULL DEFAULT 0 AFTER permite_adjuntos',
  'SELECT 1'
);

PREPARE stmt_habilitado_mobile FROM @sql_habilitado_mobile;
EXECUTE stmt_habilitado_mobile;
DEALLOCATE PREPARE stmt_habilitado_mobile;

SET @idx_habilitado_mobile := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'legajo_tipos_evento'
    AND INDEX_NAME = 'idx_legajo_tipos_evento_mobile'
);

SET @sql_idx_habilitado_mobile := IF(
  @idx_habilitado_mobile = 0,
  'CREATE INDEX idx_legajo_tipos_evento_mobile ON legajo_tipos_evento (activo, habilitado_mobile)',
  'SELECT 1'
);

PREPARE stmt_idx_habilitado_mobile FROM @sql_idx_habilitado_mobile;
EXECUTE stmt_idx_habilitado_mobile;
DEALLOCATE PREPARE stmt_idx_habilitado_mobile;
