-- Módulo: Registro de sesiones mobile (login + último request)
-- Fecha: 2026-05-24

CREATE TABLE IF NOT EXISTS mobile_sesiones (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    empleado_id           INT NOT NULL,
    dni                   VARCHAR(20) NOT NULL,
    ip                    VARCHAR(45) NULL,
    platform              VARCHAR(10) NULL,        -- android | ios
    device_model          VARCHAR(100) NULL,
    app_version           VARCHAR(30) NULL,
    fecha_login           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_ultimo_request  DATETIME NULL,

    INDEX idx_ms_empleado  (empleado_id),
    INDEX idx_ms_fecha     (fecha_login),
    INDEX idx_ms_platform  (platform),
    INDEX idx_ms_version   (app_version),

    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
