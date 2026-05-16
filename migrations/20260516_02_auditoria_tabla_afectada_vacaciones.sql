-- Migracion: agrega 'vacaciones_movimientos' al ENUM tabla_afectada de auditoria
-- Fecha: 2026-05-16
-- Si tabla_afectada es VARCHAR, esta migracion es un no-op seguro.
-- Si es ENUM, agrega el nuevo valor sin romper datos existentes.

SET @col_type := (
  SELECT COLUMN_TYPE
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'auditoria'
    AND COLUMN_NAME = 'tabla_afectada'
  LIMIT 1
);

-- Solo ejecuta el ALTER si la columna es un ENUM y el valor aun no esta incluido
SET @needs_alter := (
  @col_type LIKE 'enum(%'
  AND @col_type NOT LIKE '%vacaciones_movimientos%'
);

-- Construye el nuevo ENUM agregando 'vacaciones_movimientos'
SET @new_enum := IF(
  @needs_alter,
  CONCAT(LEFT(@col_type, LENGTH(@col_type) - 1), ",'vacaciones_movimientos')"),
  NULL
);

SET @sql := IF(
  @needs_alter AND @new_enum IS NOT NULL,
  CONCAT('ALTER TABLE auditoria MODIFY COLUMN tabla_afectada ', @new_enum, ' NOT NULL'),
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
