-- Migration: rango explicito para justificaciones
-- Date: 2026-07-09
-- Notes:
--   - Agrega justificaciones.fecha_desde y justificaciones.fecha_hasta.
--   - Backfill para mantener compatibilidad con registros existentes.
--   - Indexa empleado + rango para consultas de solapamiento.

SET @fecha_desde_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'fecha_desde'
);

SET @sql := IF(
  @fecha_desde_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN fecha_desde DATE NULL AFTER fecha',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @fecha_hasta_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'fecha_hasta'
);

SET @sql := IF(
  @fecha_hasta_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN fecha_hasta DATE NULL AFTER fecha_desde',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @old_safe_updates := @@SQL_SAFE_UPDATES;
SET SQL_SAFE_UPDATES = 0;

UPDATE justificaciones
SET
  fecha_desde = COALESCE(fecha_desde, fecha),
  fecha_hasta = COALESCE(fecha_hasta, fecha)
WHERE fecha_desde IS NULL
   OR fecha_hasta IS NULL;

SET SQL_SAFE_UPDATES = @old_safe_updates;

SET @fecha_desde_nullable := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'fecha_desde'
    AND IS_NULLABLE = 'YES'
);

SET @fecha_hasta_nullable := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'fecha_hasta'
    AND IS_NULLABLE = 'YES'
);

SET @sql := IF(
  @fecha_desde_nullable > 0 AND @fecha_hasta_nullable > 0,
  'ALTER TABLE justificaciones MODIFY fecha_desde DATE NOT NULL, MODIFY fecha_hasta DATE NOT NULL',
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
    AND index_name = 'idx_justificaciones_empleado_fechas'
);

SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE justificaciones ADD INDEX idx_justificaciones_empleado_fechas (empleado_id, fecha_desde, fecha_hasta, estado)',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
