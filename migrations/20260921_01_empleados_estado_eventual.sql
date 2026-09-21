-- Append the new value to preserve existing ENUM positions and employee states.
ALTER TABLE empleados
  MODIFY COLUMN estado ENUM('activo', 'inactivo', 'suspendido', 'eventual')
  NULL DEFAULT 'activo';
