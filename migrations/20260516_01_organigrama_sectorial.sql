-- Migracion: jerarquia y responsables de sectores para organigrama
-- Fecha: 2026-05-16

SET @sector_padre_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'sectores'
    AND COLUMN_NAME = 'sector_padre_id'
);

SET @alter_sector_padre_sql := IF(
  @sector_padre_exists = 0,
  'ALTER TABLE sectores ADD COLUMN sector_padre_id INT NULL AFTER empresa_id',
  'SELECT 1'
);

PREPARE stmt FROM @alter_sector_padre_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @responsable_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'sectores'
    AND COLUMN_NAME = 'responsable_empleado_id'
);

SET @alter_responsable_sql := IF(
  @responsable_exists = 0,
  'ALTER TABLE sectores ADD COLUMN responsable_empleado_id INT NULL AFTER sector_padre_id',
  'SELECT 1'
);

PREPARE stmt FROM @alter_responsable_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_sector_padre_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'sectores'
    AND INDEX_NAME = 'idx_sectores_sector_padre'
);

SET @idx_sector_padre_sql := IF(
  @idx_sector_padre_exists = 0,
  'ALTER TABLE sectores ADD INDEX idx_sectores_sector_padre (sector_padre_id)',
  'SELECT 1'
);

PREPARE stmt FROM @idx_sector_padre_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_responsable_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'sectores'
    AND INDEX_NAME = 'idx_sectores_responsable'
);

SET @idx_responsable_sql := IF(
  @idx_responsable_exists = 0,
  'ALTER TABLE sectores ADD INDEX idx_sectores_responsable (responsable_empleado_id)',
  'SELECT 1'
);

PREPARE stmt FROM @idx_responsable_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @fk_sector_padre_exists := (
  SELECT COUNT(*)
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'sectores'
    AND CONSTRAINT_NAME = 'fk_sectores_sector_padre'
);

SET @fk_sector_padre_sql := IF(
  @fk_sector_padre_exists = 0,
  'ALTER TABLE sectores ADD CONSTRAINT fk_sectores_sector_padre FOREIGN KEY (sector_padre_id) REFERENCES sectores (id) ON DELETE SET NULL',
  'SELECT 1'
);

PREPARE stmt FROM @fk_sector_padre_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @fk_responsable_exists := (
  SELECT COUNT(*)
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'sectores'
    AND CONSTRAINT_NAME = 'fk_sectores_responsable'
);

SET @fk_responsable_sql := IF(
  @fk_responsable_exists = 0,
  'ALTER TABLE sectores ADD CONSTRAINT fk_sectores_responsable FOREIGN KEY (responsable_empleado_id) REFERENCES empleados (id) ON DELETE SET NULL',
  'SELECT 1'
);

PREPARE stmt FROM @fk_responsable_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
