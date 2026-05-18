-- Migracion: tabla de configuracion de versiones de la app mobile
-- Fecha: 2026-05-18

CREATE TABLE IF NOT EXISTS app_version_config (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  platform ENUM('android', 'ios', 'all') NOT NULL DEFAULT 'all',
  version_minima VARCHAR(20) NOT NULL DEFAULT '1.0.0',
  version_recomendada VARCHAR(20) NOT NULL DEFAULT '1.0.0',
  url_descarga VARCHAR(500) NULL,
  mensaje VARCHAR(500) NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_app_version_platform (platform, activo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Fila inicial: plataforma android con version 1.0.0
-- Ajustar version_minima y version_recomendada segun corresponda
INSERT INTO app_version_config (platform, version_minima, version_recomendada, url_descarga, mensaje)
VALUES (
  'android',
  '1.0.0',
  '1.0.0',
  NULL,
  'Hay una nueva versión disponible. Actualizá para seguir usando la app.'
)
ON DUPLICATE KEY UPDATE id = id;
