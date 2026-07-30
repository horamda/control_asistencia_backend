-- Migration: resolucion y notificacion de justificaciones
-- Date: 2026-07-23
-- Notes:
--   - Guarda quien resolvio, fecha de resolucion, comentario/motivo de rechazo.
--   - Permite que mobile marque una resolucion como vista por el empleado.

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'resuelto_by_usuario_id'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN resuelto_by_usuario_id INT NULL AFTER estado',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'resuelto_at'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN resuelto_at DATETIME NULL AFTER resuelto_by_usuario_id',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'comentario_resolucion'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN comentario_resolucion TEXT NULL AFTER resuelto_at',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'motivo_rechazo'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN motivo_rechazo TEXT NULL AFTER comentario_resolucion',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'notificado_empleado_at'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN notificado_empleado_at DATETIME NULL AFTER motivo_rechazo',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE table_schema = DATABASE()
    AND table_name = 'justificaciones'
    AND column_name = 'visto_por_empleado_at'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE justificaciones ADD COLUMN visto_por_empleado_at DATETIME NULL AFTER notificado_empleado_at',
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
    AND index_name = 'idx_justificaciones_estado_notificacion'
);

SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE justificaciones ADD INDEX idx_justificaciones_estado_notificacion (empleado_id, estado, resuelto_at, visto_por_empleado_at)',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
