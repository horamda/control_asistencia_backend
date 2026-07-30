ALTER TABLE empleados
  ADD COLUMN requiere_control_asistencia TINYINT(1) NOT NULL DEFAULT 1 AFTER activo;

CREATE INDEX idx_empleados_control_asistencia
  ON empleados (activo, requiere_control_asistencia);
