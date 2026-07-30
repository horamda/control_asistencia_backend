-- Tabla generica de configuracion de sistema (clave/valor).
-- Primer uso: detectar cambios accidentales de JWT_SECRET entre deploys.
-- Fecha: 2026-07-15

CREATE TABLE IF NOT EXISTS system_config (
    config_key   VARCHAR(100) NOT NULL,
    config_value VARCHAR(255) NOT NULL,
    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
