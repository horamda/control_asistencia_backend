-- Migracion: los motivos de feedback pasan a pertenecer a un sector especifico.
-- Ventas y Operaciones (por ejemplo) pueden tener motivos distintos; ya no es
-- un catalogo global compartido. La columna se agrega NULL a nivel de base de
-- datos para no romper motivos ya existentes, pero el alta/edicion en el panel
-- exige seleccionar un sector siempre.
-- Fecha: 2026-07-21

ALTER TABLE feedback_motivos
  ADD COLUMN sector_id INT NULL AFTER nombre,
  ADD KEY idx_feedback_motivos_sector (sector_id),
  ADD CONSTRAINT fk_feedback_motivos_sector FOREIGN KEY (sector_id) REFERENCES sectores (id) ON DELETE RESTRICT;

-- El nombre dejaba de ser unico globalmente: dos sectores distintos pueden
-- tener cada uno un motivo "Otro". Se reemplaza la unicidad global por
-- unicidad (sector_id, nombre).
ALTER TABLE feedback_motivos
  DROP INDEX uq_feedback_motivo_nombre,
  ADD UNIQUE KEY uq_feedback_motivo_sector_nombre (sector_id, nombre);
