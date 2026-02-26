ALTER TABLE asistencia_marcas
  ADD COLUMN IF NOT EXISTS tipo_marca VARCHAR(20) NOT NULL DEFAULT 'jornada' AFTER metodo;

ALTER TABLE qr_puerta_historial
  ADD COLUMN IF NOT EXISTS tipo_marca VARCHAR(20) NOT NULL DEFAULT 'jornada' AFTER sucursal_nombre;
