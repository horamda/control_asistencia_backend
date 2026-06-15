-- Migration: justificaciones vinculadas a legajos con adjuntos normalizados
-- Date: 2026-06-08
-- Notes:
--   - Indexa legajo_eventos.justificacion_id para resolver el evento asociado a una justificacion.
--   - Agrega un tipo de evento especifico para justificaciones.

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'legajo_eventos'
    AND index_name = 'idx_legajo_eventos_justificacion'
);

SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE legajo_eventos ADD INDEX idx_legajo_eventos_justificacion (justificacion_id)',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT IGNORE INTO legajo_tipos_evento (
  codigo,
  nombre,
  requiere_rango_fechas,
  permite_adjuntos,
  activo
) VALUES (
  'justificacion',
  'Justificacion de asistencia',
  0,
  1,
  1
);
