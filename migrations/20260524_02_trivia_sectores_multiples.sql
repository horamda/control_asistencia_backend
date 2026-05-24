-- Migración: soporte de múltiples sectores por trivia
-- Fecha: 2026-05-24
-- Reemplaza sector_id (único) por tabla de relación trivia_sectores (N sectores por trivia).
-- Sin sectores asignados = aplica a TODOS los sectores.

CREATE TABLE IF NOT EXISTS trivia_sectores (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    trivia_id  INT NOT NULL,
    sector_id  INT NOT NULL,
    UNIQUE KEY uq_ts_trivia_sector (trivia_id, sector_id),
    FOREIGN KEY (trivia_id)  REFERENCES trivias(id) ON DELETE CASCADE,
    FOREIGN KEY (sector_id)  REFERENCES sectores(id) ON DELETE CASCADE,
    INDEX idx_ts_trivia (trivia_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migrar registros existentes que tenían un único sector_id
INSERT IGNORE INTO trivia_sectores (trivia_id, sector_id)
SELECT id, sector_id
FROM trivias
WHERE sector_id IS NOT NULL;

-- La columna sector_id queda en trivias por compatibilidad pero ya no se usa en el código.
-- Se puede eliminar más adelante con:
--   ALTER TABLE trivias DROP COLUMN sector_id;
