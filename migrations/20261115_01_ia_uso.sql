-- Registro de uso de inteligencia artificial (generador de trivias y pruebas de conexion).
-- Aditiva: no toca ninguna tabla existente. No guarda contenido ni preguntas.
-- Reversion: DROP TABLE ia_uso; DELETE FROM system_config WHERE config_key LIKE 'ia\_%';

CREATE TABLE IF NOT EXISTS ia_uso (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  creado_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  usuario_id     INT          NULL,
  proveedor      VARCHAR(20)  NOT NULL,
  modelo         VARCHAR(120) NOT NULL,
  operacion      VARCHAR(20)  NOT NULL,
  estado         VARCHAR(10)  NOT NULL,
  error_tipo     VARCHAR(20)  NULL,
  tokens_entrada INT          NOT NULL DEFAULT 0,
  tokens_salida  INT          NOT NULL DEFAULT 0,
  costo_usd      DECIMAL(10,4) NOT NULL DEFAULT 0,
  duracion_ms    INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_ia_uso_fecha (creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
