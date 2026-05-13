ALTER TABLE qr_puerta_historial
  ADD COLUMN IF NOT EXISTS qr_token_hash CHAR(64) NULL AFTER qr_token,
  ADD COLUMN IF NOT EXISTS activo TINYINT(1) NOT NULL DEFAULT 1 AFTER usuario_id,
  ADD COLUMN IF NOT EXISTS inactivado_at DATETIME NULL AFTER activo,
  ADD COLUMN IF NOT EXISTS inactivado_by_usuario INT NULL AFTER inactivado_at,
  ADD COLUMN IF NOT EXISTS inactivado_motivo VARCHAR(255) NULL AFTER inactivado_by_usuario;

UPDATE qr_puerta_historial
SET qr_token_hash = SHA2(qr_token, 256)
WHERE qr_token_hash IS NULL OR qr_token_hash = '';

CREATE INDEX idx_qr_puerta_historial_token_hash
  ON qr_puerta_historial (qr_token_hash);

CREATE INDEX idx_qr_puerta_historial_activo_fecha
  ON qr_puerta_historial (activo, fecha);
