-- Migracion: exclusiones del ranking anual de trivias
-- Fecha: 2026-05-28
-- Permite excluir empleados puntuales del ranking anual sin modificar resultados historicos.

CREATE TABLE IF NOT EXISTS trivia_ranking_anual_exclusiones (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    anio        SMALLINT NOT NULL,
    empleado_id INT NOT NULL,
    motivo      VARCHAR(300) NULL,
    creado_por  INT NULL,
    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_trae_anio_empleado (anio, empleado_id),
    KEY idx_trae_anio (anio),
    KEY idx_trae_empleado (empleado_id),
    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
