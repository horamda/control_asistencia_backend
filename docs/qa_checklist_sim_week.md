# Checklist QA - Simulacion semanal (SIMW260302)

## Objetivo
Validar que los datos de asistencia, marcas y reportes reflejen correctamente:
- Turno cortado (varios ingresos/egresos en un dia)
- Mezcla QR/manual
- Llegadas tarde
- Salida anticipada
- Ausencias
- Comportamiento explicito de fin de semana

## Preparacion
1. Ejecutar seed limpio/repetible:
```powershell
.\venv\Scripts\python.exe scripts\sim_week_seed.py --tag SIMW260302 --start-date 2026-02-23
```
2. Verificar resumen impreso por script.

## Resultados esperados del dataset
1. Empleados simulados: `8` (legajos `SIMW260302-001` a `SIMW260302-008`).
2. Rango: `2026-02-23` a `2026-03-01` (7 dias).
3. Asistencias: `77`.
4. Marcas: `150`.
5. Asistencias por fecha:
- 2026-02-23: 15
- 2026-02-24: 15
- 2026-02-25: 14
- 2026-02-26: 15
- 2026-02-27: 14
- 2026-02-28: 2
- 2026-03-01: 2
6. Estados esperados (total):
- `ausente`: 2
- `ok`: 66
- `tarde`: 4
- `salida_anticipada`: 5

## Pruebas funcionales en panel
1. Dashboard:
- Cargar `/dashboard` sin 500.
- Confirmar que aparecen movimientos del rango (incluye sabado/domingo).

2. Asistencias listado:
- Filtrar por legajo `SIMW260302-003`, fecha `2026-02-23`.
- Validar secuencia: `ingreso qr -> egreso manual -> ingreso qr -> egreso qr`.
- Filtrar por `SIMW260302-004` y fecha `2026-02-25`:
  debe existir una asistencia `ausente` sin horas.

3. Marcas:
- Revisar `/asistencias/marcas` para `SIMW260302-008` y `2026-02-26`.
- Validar caso: egreso manual intermedio + nuevo ingreso QR.

4. Filtros por estado:
- `tarde`: debe incluir a `SIMW260302-002` (martes y jueves).
- `salida_anticipada`: debe incluir a `SIMW260302-005` y `SIMW260302-008`.
- `ausente`: debe incluir a `SIMW260302-004` y `SIMW260302-005`.

5. Vacaciones y justificaciones:
- Vacaciones: `SIMW260302-002` (proximas) y `SIMW260302-007` (en curso).
- Justificaciones: 3 registros asociados al dataset.

## Consultas SQL rapidas de control
```sql
-- Empleados simulados
SELECT id, legajo, nombre, apellido
FROM empleados
WHERE legajo LIKE 'SIMW260302-%'
ORDER BY id;

-- Totales
SELECT COUNT(*) AS asistencias
FROM asistencias a
JOIN empleados e ON e.id = a.empleado_id
WHERE e.legajo LIKE 'SIMW260302-%'
  AND a.fecha BETWEEN '2026-02-23' AND '2026-03-01';

SELECT COUNT(*) AS marcas
FROM asistencia_marcas am
JOIN empleados e ON e.id = am.empleado_id
WHERE e.legajo LIKE 'SIMW260302-%'
  AND am.fecha BETWEEN '2026-02-23' AND '2026-03-01';

-- Distribucion de estados
SELECT a.estado, COUNT(*) AS total
FROM asistencias a
JOIN empleados e ON e.id = a.empleado_id
WHERE e.legajo LIKE 'SIMW260302-%'
  AND a.fecha BETWEEN '2026-02-23' AND '2026-03-01'
GROUP BY a.estado
ORDER BY a.estado;
```

## Criterio de aprobacion
Se aprueba si:
1. Los totales esperados coinciden.
2. No hay errores 500 en panel.
3. Las secuencias mixtas QR/manual se visualizan correctamente.
4. Estados y filtros muestran los casos previstos.
