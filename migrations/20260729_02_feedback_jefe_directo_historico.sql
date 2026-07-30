-- Corrige feedbacks historicos asignados al responsable del sector/motivo
-- en lugar del jefe directo inmediato del empleado que cargo el feedback.
--
-- Regla vigente:
--   feedbacks.jefe_directo_id y feedbacks.responsable_id deben apuntar a
--   empleados.reporta_a_empleado_id del empleado originante.
--
-- Es idempotente: solo actualiza casos donde el jefe directo actual existe,
-- esta activo y difiere del responsable guardado.

UPDATE feedbacks f
JOIN empleados origen ON origen.id = f.empleado_id
JOIN empleados jefe ON jefe.id = origen.reporta_a_empleado_id AND jefe.activo = 1
SET
    f.jefe_directo_id = jefe.id,
    f.responsable_id = jefe.id,
    f.jefe_directo_nombre_snapshot = NULLIF(TRIM(CONCAT(COALESCE(jefe.apellido, ''), ' ', COALESCE(jefe.nombre, ''))), ''),
    f.updated_at = CURRENT_TIMESTAMP
WHERE origen.reporta_a_empleado_id IS NOT NULL
  AND origen.reporta_a_empleado_id > 0
  AND f.id > 0
  AND (
      f.jefe_directo_id <> jefe.id
      OR COALESCE(f.responsable_id, 0) <> jefe.id
  );

-- Verificacion opcional despues de ejecutar:
-- SELECT f.id, origen.dni AS empleado_dni, jefe.dni AS jefe_directo_dni,
--        f.jefe_directo_id, f.responsable_id
-- FROM feedbacks f
-- JOIN empleados origen ON origen.id = f.empleado_id
-- JOIN empleados jefe ON jefe.id = origen.reporta_a_empleado_id
-- WHERE origen.dni = '35083048';
