# Rendimiento del panel: 15 de septiembre de 2026

## Cambios

- Empleados: resumen de vacaciones por lote para los empleados de la pagina.
  Antes: hasta tres consultas por empleado (empleado, dias trabajados, movimientos).
  Ahora: dos consultas por pagina, reutilizando los datos de empleados ya leidos.
  Las fechas trabajadas se cargan solo para el anio y empleados solicitados;
  el calculo conserva ingreso, baja, proporcionalidad, pendientes y reversiones.
- Empleados/legajos: se eliminaron los agrupamientos globales de eventos y puestos
  adicionales. Las estadisticas se consultan por empleado y los filtros usan
  EXISTS/NOT EXISTS. El conteo de empleados ya no agrupa toda la tabla de eventos.
- Dashboard: cuatro consultas de justificaciones mensuales se convirtieron en una.
  El filtro usa `created_at >= inicio AND created_at < dia_siguiente`, manteniendo
  todo el ultimo dia y permitiendo usar el indice de fecha.
- Premios: filtros por anio y anio/mes usan rangos de fechas sobre `periodo`.
  El filtro de mes sin anio conserva MONTH porque debe incluir todos los anios.
- Se mantienen las mejoras anteriores de agrupacion de contadores de asistencia.

## Indices aplicados

Se crearon en la base configurada en este entorno:

- `justificaciones (created_at, estado)`: `idx_just_created_estado`.
- `asistencias (fecha, estado)`: `idx_asistencias_fecha_estado`.

Se uso ALTER TABLE con `ALGORITHM=INPLACE, LOCK=NONE` y espera de metadata lock
de cinco segundos. La segunda ejecucion detecto ambos indices y no los recreo.
No se eliminaron indices anteriores. Estos indices ocupan espacio y agregan un
pequeno costo a las escrituras a cambio de cubrir las consultas de resumen.

Auditoria o aplicacion en otro entorno:

```powershell
python scripts/migrate_20260915_02_panel_indexes.py
python scripts/migrate_20260915_02_panel_indexes.py --apply
```

Sin `--apply` solo consulta metadatos y EXPLAIN. Detecta indices equivalentes
por sus columnas iniciales, aunque tengan otro nombre. Si MySQL no soporta la
creacion sin bloquear escrituras, falla; no cambia a una operacion bloqueante.

## Evidencia

- 80 pruebas de vacaciones, listados, legajos, premios, dashboard y consultas.
- Comparacion MySQL de cuatro variantes del listado de empleados: resultados
  completos y totales identicos (general, con eventos, sin eventos y vigentes).
- Comparacion MySQL de resumenes de vacaciones: 20 empleados, todos identicos.
  Tiempo de esa operacion: **26.226,2 ms antes / 741,9 ms despues**.
  Es una sola muestra, sobre una transaccion de lectura consistente, con latencia
  de red incluida. No representa el tiempo total del panel ni una garantia de SLA.
- El par de consultas del listado, sin vacaciones, tuvo medianas de 663,3 ms y
  656,8 ms en tres ejecuciones. Esa diferencia pequena no demuestra por si sola
  una mejora estable; la reduccion importante fue quitar las consultas por persona.
- EXPLAIN de asistencias paso de `idx_asistencias_fecha_id` con acceso adicional
  a filas a `idx_asistencias_fecha_estado` con `Using index`.
- EXPLAIN del resumen mensual de justificaciones paso de `ALL` sin indice a
  `range` con `idx_just_created_estado` y `Using index`. La tabla actual es pequena;
  no se presenta ese cambio como una gran mejora de tiempo medida.

## Despliegue

Los indices ya se aplicaron a la base conectada. Los cambios Python siguen en
el workspace y requieren desplegar/reiniciar el backend para que el panel use
la lectura por lote y las nuevas consultas. No se cambiaron registros de negocio.

La base tiene indices de asistencia duplicados por distintas migraciones previas.
No se eliminaron: su limpieza requiere revisar claves foraneas, otras consultas
y el codigo de inicializacion que podria volver a crearlos.
