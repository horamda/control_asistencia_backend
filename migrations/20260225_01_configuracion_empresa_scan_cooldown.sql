ALTER TABLE configuracion_empresa
  ADD COLUMN IF NOT EXISTS cooldown_scan_segundos INT NULL AFTER tolerancia_global;
