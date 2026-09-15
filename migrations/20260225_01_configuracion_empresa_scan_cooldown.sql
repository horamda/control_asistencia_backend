SET @schema_name = DATABASE();

SET @column_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'configuracion_empresa'
    AND COLUMN_NAME = 'cooldown_scan_segundos'
);

SET @sql := IF(
  @column_exists = 0,
  'ALTER TABLE configuracion_empresa ADD COLUMN cooldown_scan_segundos INT NULL AFTER tolerancia_global',
  'SELECT ''skip configuracion_empresa.cooldown_scan_segundos'' AS info'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
