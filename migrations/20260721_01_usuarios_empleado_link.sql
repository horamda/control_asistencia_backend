-- Migracion: vincula un usuario del panel administrativo a un legajo de empleado.
-- Permite que un jefe directo (empleado) inicie sesion en el panel y opere
-- su propia bandeja de feedback (y a futuro, otras vistas "de mis subordinados").
-- Fecha: 2026-07-21

ALTER TABLE usuarios
  ADD COLUMN empleado_id INT NULL AFTER empresa_id,
  ADD KEY idx_usuarios_empleado (empleado_id),
  ADD CONSTRAINT fk_usuarios_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id) ON DELETE SET NULL;
