-- Migracion: movimientos de vacaciones para API mobile
-- Fecha: 2026-05-15

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Ejecutar solo si la base historica no tiene fecha_ingreso.
-- Algunas instalaciones ya la tienen creada por migraciones anteriores.
SET @fecha_ingreso_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'empleados'
    AND COLUMN_NAME = 'fecha_ingreso'
);

SET @alter_fecha_ingreso_sql := IF(
  @fecha_ingreso_exists = 0,
  'ALTER TABLE empleados ADD COLUMN fecha_ingreso DATE NULL AFTER fecha_nacimiento',
  'SELECT 1'
);

PREPARE stmt FROM @alter_fecha_ingreso_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
