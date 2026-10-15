-- Metricas de rendimiento del panel (modulo Rendimiento): pedidos agregados
-- por hora (Argentina, UTC-3), ruta y metodo. Las escribe utils/request_metrics.py.
CREATE TABLE IF NOT EXISTS request_metrics_hourly (
  hora          DATETIME     NOT NULL,
  ruta          VARCHAR(190) NOT NULL,
  metodo        VARCHAR(8)   NOT NULL,
  pedidos       INT UNSIGNED NOT NULL DEFAULT 0,
  errores       INT UNSIGNED NOT NULL DEFAULT 0,
  ms_total      DOUBLE       NOT NULL DEFAULT 0,
  ms_max        DOUBLE       NOT NULL DEFAULT 0,
  db_ms_total   DOUBLE       NOT NULL DEFAULT 0,
  db_consultas  INT UNSIGNED NOT NULL DEFAULT 0,
  b100          INT UNSIGNED NOT NULL DEFAULT 0,
  b250          INT UNSIGNED NOT NULL DEFAULT 0,
  b500          INT UNSIGNED NOT NULL DEFAULT 0,
  b1000         INT UNSIGNED NOT NULL DEFAULT 0,
  b2000         INT UNSIGNED NOT NULL DEFAULT 0,
  b5000         INT UNSIGNED NOT NULL DEFAULT 0,
  binf          INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (hora, ruta, metodo),
  KEY idx_request_metrics_hora (hora)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
