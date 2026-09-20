CREATE TABLE IF NOT EXISTS trivia_ranking_exclusiones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trivia_id INT NOT NULL,
    empleado_id INT NOT NULL,
    motivo VARCHAR(300) NULL,
    creado_por INT NULL,
    creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_tre_trivia_empleado (trivia_id, empleado_id),
    FOREIGN KEY (trivia_id) REFERENCES trivias(id) ON DELETE CASCADE,
    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
