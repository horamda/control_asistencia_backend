-- Migration: almacenamiento binario de adjuntos de legajo en DB
-- Date: 2026-03-07
-- Notes:
--   - Guarda el PDF final optimizado en tabla separada para evitar cargar blobs en listados.

CREATE TABLE IF NOT EXISTS legajo_evento_adjuntos_db (
  adjunto_id BIGINT UNSIGNED NOT NULL,
  data LONGBLOB NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (adjunto_id),
  CONSTRAINT fk_legajo_adjuntos_db_adjunto
    FOREIGN KEY (adjunto_id) REFERENCES legajo_evento_adjuntos (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
