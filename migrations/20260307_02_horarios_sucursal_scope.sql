-- Migration: scope empresa/sucursal para plantillas de horarios
-- Date: 2026-03-07
-- Notes:
--   - Agrega sucursal_id a horarios para segmentar plantillas por sucursal.
--   - Deja la columna nullable por compatibilidad con datos legacy.

SET @db_name := DATABASE();

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'horarios'
    AND COLUMN_NAME = 'sucursal_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE horarios ADD COLUMN sucursal_id INT NULL AFTER empresa_id',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'horarios'
    AND INDEX_NAME = 'idx_horarios_sucursal_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE horarios ADD INDEX idx_horarios_sucursal_id (sucursal_id)',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @fk_exists := (
  SELECT COUNT(*)
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = @db_name
    AND TABLE_NAME = 'horarios'
    AND CONSTRAINT_NAME = 'fk_horarios_sucursal'
);
SET @sql := IF(
  @fk_exists = 0,
  'ALTER TABLE horarios ADD CONSTRAINT fk_horarios_sucursal FOREIGN KEY (sucursal_id) REFERENCES sucursales(id) ON DELETE SET NULL ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
