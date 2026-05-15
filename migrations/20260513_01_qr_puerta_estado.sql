DROP PROCEDURE IF EXISTS migrate_20260513_01_qr_puerta_estado;

DELIMITER //
CREATE PROCEDURE migrate_20260513_01_qr_puerta_estado()
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND COLUMN_NAME = 'qr_token_hash'
  ) THEN
    ALTER TABLE qr_puerta_historial
      ADD COLUMN qr_token_hash CHAR(64) NULL AFTER qr_token;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND COLUMN_NAME = 'activo'
  ) THEN
    ALTER TABLE qr_puerta_historial
      ADD COLUMN activo TINYINT NOT NULL DEFAULT 1 AFTER usuario_id;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND COLUMN_NAME = 'inactivado_at'
  ) THEN
    ALTER TABLE qr_puerta_historial
      ADD COLUMN inactivado_at DATETIME NULL AFTER activo;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND COLUMN_NAME = 'inactivado_by_usuario'
  ) THEN
    ALTER TABLE qr_puerta_historial
      ADD COLUMN inactivado_by_usuario INT NULL AFTER inactivado_at;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND COLUMN_NAME = 'inactivado_motivo'
  ) THEN
    ALTER TABLE qr_puerta_historial
      ADD COLUMN inactivado_motivo VARCHAR(255) NULL AFTER inactivado_by_usuario;
  END IF;

  UPDATE qr_puerta_historial
  SET qr_token_hash = SHA2(qr_token, 256)
  WHERE id > 0
    AND (qr_token_hash IS NULL OR qr_token_hash = '');

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND INDEX_NAME = 'idx_qr_puerta_historial_token_hash'
  ) THEN
    CREATE INDEX idx_qr_puerta_historial_token_hash
      ON qr_puerta_historial (qr_token_hash);
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'qr_puerta_historial'
      AND INDEX_NAME = 'idx_qr_puerta_historial_activo_fecha'
  ) THEN
    CREATE INDEX idx_qr_puerta_historial_activo_fecha
      ON qr_puerta_historial (activo, fecha);
  END IF;
END//
DELIMITER ;

CALL migrate_20260513_01_qr_puerta_estado();

DROP PROCEDURE IF EXISTS migrate_20260513_01_qr_puerta_estado;
