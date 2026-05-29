-- Migracion: exclusiones por trivia
-- Fecha: 2026-05-27
-- Permite excluir empleados puntuales sin modificar el alcance por sectores.

CREATE TABLE IF NOT EXISTS trivia_exclusiones (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    trivia_id   INT NOT NULL,
    empleado_id INT NOT NULL,
    motivo      VARCHAR(300) NULL,
    creado_por  INT NULL,
    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_te_trivia_empleado (trivia_id, empleado_id),
    FOREIGN KEY (trivia_id) REFERENCES trivias(id) ON DELETE CASCADE,
    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE,
    INDEX idx_te_trivia (trivia_id),
    INDEX idx_te_empleado (empleado_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
