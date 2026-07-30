-- Modulo: Feedback - evidencia fotografica
-- Fecha: 2026-07-22

ALTER TABLE feedbacks
    ADD COLUMN evidencia_filename VARCHAR(255) NULL AFTER resolucion_descripcion,
    ADD COLUMN evidencia_path VARCHAR(500) NULL AFTER evidencia_filename,
    ADD COLUMN evidencia_mime_type VARCHAR(100) NULL AFTER evidencia_path,
    ADD COLUMN evidencia_size_bytes INT NULL AFTER evidencia_mime_type;
