# Asistencias manuales y coherencia de reportes

Cambios del 20/09/2026:

- Alta, edicion y eliminacion administrativa coordinan resumen diario, marcas,
  estado y auditoria en una transaccion. Un error revierte toda la operacion.
- La correccion de una marca recalcula el estado usando el horario esperado.
  Conserva su identificador y metodo original; agrega `corregida_manualmente`.
- Las marcas nuevas del panel se registran como manuales, sin atribuirles GPS
  o foto de una marcacion anterior.
- `asistencia_correcciones` conserva usuario, momento, accion y valores antes/despues.
- El formulario de resumen rechaza jornadas con varias marcas o movimientos
  especiales antes de guardar. Deben corregirse desde la marca concreta en la
  planilla diaria. Tambien rechaza otra asistencia o marcas ajenas al resumen
  para la misma persona y fecha.
- Al borrar una asistencia desde el panel se borran sus marcas vinculadas,
  conservando el registro de auditoria, para evitar movimientos sin resumen.

La vista `asistencia_marcas_reporte` consulta marcas reales y agrega movimientos
virtuales de resumen solo si no hay ninguna marca real de esa persona y fecha.
La usan el historial web/movil, los reportes mensuales y las exportaciones de marcas.
No inserta ni modifica datos historicos. Las planillas y presencia conservan su
prioridad por marcas y su respaldo historico. Las estadisticas moviles siguen
leyendo el resumen, actualizado en la misma transaccion.

Las exportaciones web y los reportes mensuales ya no tienen el recorte implicito
de 10.000/20.000 marcas. La API externa conserva su parametro `limit` documentado;
para periodos extensos debe consultarse por rangos. El CSV estandar de integracion
conserva sus ocho columnas; el CSV detallado agrega las dos marcas booleanas.
El historial web y Excel identifican correcciones. Flutter muestra la condicion
en el detalle de marca. Contrato movil: 1.29.0.

Los cambios aparecen al volver a consultar. Los archivos descargados y pantallas
ya abiertas necesitan regenerarse o refrescarse. La migracion no puede identificar
retroactivamente todas las correcciones manuales anteriores.

## Instalacion

Antes de desplegar el backend en otro entorno:

```powershell
python scripts/migrate_20260920_03_asistencia_reportes.py
```

Crea la columna de correccion, tabla de auditoria y vista de consulta. Es idempotente.
Aplicada a la base configurada el 20/09/2026. No se corrigieron horarios historicos.
El script es la entrada completa de migracion; el SQL de la vista requiere los
metadatos creados primero por el script.

## Auditoria de la base configurada

```powershell
python scripts/audit_asistencia_consistency.py
```

Resultado al implementar:

| Control | Cantidad |
|---|---:|
| Resumenes examinados | 3366 |
| Resumenes con horarios pero sin marcas del dia | 0 |
| Resumenes ausentes con horarios | 0 |
| Diferencias de horario entre resumen y marcas vinculadas | 0 |
| Marcas con empleado/empresa/fecha distintos del resumen vinculado | 0 |
| Marcas que referencian un resumen inexistente | 9 |

Las nueve marcas corresponden a una jornada QR de mayo y ocho marcas manuales
entre el 1 y el 13 de julio de 2026. No hay resumen alternativo de la misma persona
y fecha. Se conservaron sin cambios: no se puede inferir si el borrado fue intencional.
El detalle para revision esta en `instance/attendance_audit/marcas_sin_resumen.csv`
(fuera de Git). No se incluyen nombres ni credenciales en este documento.

La auditoria compara horarios y relaciones, no reconstruye estados historicos contra
asignaciones de horario anteriores. Las nuevas ediciones recalculan el estado con
la configuracion de horario vigente para la fecha consultada.

## Validacion

Pruebas SQL aisladas: creacion, correccion, recambio de estado, preservacion de IDs,
rechazo de jornadas ambiguas, rollback, eliminacion, respaldo historico sin duplicados,
mas de 20.000 marcas y efecto sobre el reporte mensual. Pruebas HTTP web/API, exportaciones,
paginacion y compatibilidad Flutter. Lecturas reales de la nueva vista verificadas.
Pendiente desplegar backend y distribuir Flutter; no se verifico visualmente en produccion.
