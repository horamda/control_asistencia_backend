-- Migration: fecha explicita para justificaciones
-- Date: 2026-06-23
-- Notes:
--   - Agrega justificaciones.fecha para guardar el dia justificado.
--   - Backfill para registros existentes desde asistencia.fecha o created_at.
--   - Indexa empleado + fecha para consultas y validaciones.

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'fecha'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN fecha DATE NULL AFTER asistencia_id',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @old_safe_updates := @@SQL_SAFE_UPDATES;
SET SQL_SAFE_UPDATES = 0;

UPDATE justificaciones j
LEFT JOIN asistencias a ON a.id = j.asistencia_id
SET j.fecha = COALESCE(j.fecha, a.fecha, DATE(j.created_at))
WHERE j.fecha IS NULL;

SET SQL_SAFE_UPDATES = @old_safe_updates;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'fecha'
    AND IS_NULLABLE = 'YES'
);

SET @sql := IF(
  @col_exists > 0,
  'ALTER TABLE justificaciones MODIFY fecha DATE NOT NULL',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND index_name = 'idx_justificaciones_empleado_fecha'
);

SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE justificaciones ADD INDEX idx_justificaciones_empleado_fecha (empleado_id, fecha, estado)',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
