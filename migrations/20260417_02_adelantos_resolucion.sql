-- Migracion: metadatos de resolucion para adelantos
-- Fecha: 2026-04-17

ALTER TABLE adelantos
    ADD COLUMN resuelto_by_usuario_id INT NULL AFTER estado,
    ADD COLUMN resuelto_at DATETIME NULL AFTER resuelto_by_usuario_id,
    ADD INDEX idx_adelantos_resuelto_by (resuelto_by_usuario_id);
