-- Módulo: Calificación de experiencia de uso de la app
-- Fecha: 2026-05-24

CREATE TABLE IF NOT EXISTS app_calificaciones (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    empleado_id   INT NOT NULL,
    dni           VARCHAR(20) NOT NULL,
    puntuacion    TINYINT NOT NULL,
    comentario    TEXT NULL,
    pantalla      VARCHAR(100) NULL,
    version_app   VARCHAR(30) NULL,
    fecha         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_puntuacion CHECK (puntuacion BETWEEN 1 AND 5),

    -- Un empleado puede calificar una sola vez por versión de app.
    -- version_app NULL = versión desconocida (se controla a nivel aplicación,
    -- ya que MySQL no trata dos NULL como iguales en UNIQUE KEY).
    UNIQUE KEY uq_empleado_version (empleado_id, version_app),

    INDEX idx_cal_fecha       (fecha),
    INDEX idx_cal_version     (version_app),
    INDEX idx_cal_puntuacion  (puntuacion),
    INDEX idx_cal_empleado    (empleado_id),

    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
