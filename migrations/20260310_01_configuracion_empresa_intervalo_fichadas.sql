ALTER TABLE configuracion_empresa
  ADD COLUMN IF NOT EXISTS intervalo_minimo_fichadas_minutos INT NULL AFTER cooldown_scan_segundos;
