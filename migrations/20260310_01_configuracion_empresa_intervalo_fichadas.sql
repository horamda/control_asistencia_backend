SET @schema_name = DATABASE();

SET @column_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'configuracion_empresa'
    AND COLUMN_NAME = 'intervalo_minimo_fichadas_minutos'
);

SET @sql := IF(
  @column_exists = 0,
  'ALTER TABLE configuracion_empresa ADD COLUMN intervalo_minimo_fichadas_minutos INT NULL AFTER cooldown_scan_segundos',
  'SELECT ''skip configuracion_empresa.intervalo_minimo_fichadas_minutos'' AS info'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
