# Velocidad e índices: cambios aplicados en Railway

El 13/10/2026 a las 20:33 UTC se retiraron tres índices secundarios duplicados de la base configurada. No se modificaron registros, claves primarias, índices únicos ni restricciones FK. La comprobación posterior confirmó que las 184 entradas de columnas de las 178 FK coinciden con la auditoría anterior.

| Tabla | Retirado | Conservado con idéntica definición |
|---|---|---|
| empleado_excepciones | idx_ee_empresa_fecha | idx_ex_emp_empresa_fecha |
| empleado_horarios | idx_empleado_horarios_vigente | idx_eh_actual |
| empleado_horarios | idx_empleado_fechas | idx_eh_empleado_rango |

Se conservaron los nombres que exige `extensions.REQUIRED_INDEXES`. No se encontraron referencias a los nombres retirados en los repositorios, migraciones y scripts inspeccionados. La mejora elimina tres estructuras que MySQL debía mantener al escribir; no se midió el aumento de capacidad de escritura con carga de producción.

## Medición

Se ejecutaron ocho SELECT mediante `EXPLAIN ANALYZE` antes y después. Estos tiempos corresponden al final del operador raíz dentro del servidor, en milisegundos; no son tiempos de carga de pantalla.

| Consulta | Antes (ms) | Después (ms) |
|---|---:|---:|
| Marcas mensuales | 4,880 | 4,600 |
| Justificaciones | 0,050 | 0,057 |
| Seguridad e Higiene | 0,093 | 0,081 |
| Vacaciones | 0,077 | 0,071 |
| Asistencias paginadas | 0,270 | 0,235 |
| Horarios | 0,007 | 0,014 |
| Excepciones | 0,016 | 0,018 |
| Sesiones móviles recientes | 0,067 | 0,083 |

Son muestras individuales con caché y carga variables, no una demostración estadística de aceleración. Vacaciones, horarios y excepciones devolvieron cero filas para los filtros seleccionados; no prueban el rendimiento con muchas coincidencias. Los planes conservaron accesos adecuados; horarios pasó del índice retirado a su equivalente conservado. No se justificó agregar índices nuevos para estas consultas con el volumen actual.

Las respuestas completas a esta PC estuvieron entre 220 y 276 ms en el corte antes/después, muy por encima del trabajo del servidor. La prueba preliminar de marcas mensuales tardó 6,89 ms en el servidor. Esto señala el costo de comunicación en este recorrido, pero no mide la conexión desde el servidor desplegado. El próximo diagnóstico de lentitud debe medir allí las rutas y su cantidad de consultas; la muestra no cubre todas las consultas ni todos los módulos.

## Ejecución y reversión

El [script](../scripts/optimize_database_indexes.py) funciona en modo lectura por defecto; `--apply` aplica únicamente los tres pares permitidos si sus definiciones coinciden y son índices no únicos. Compara columnas, orden, prefijos, visibilidad, tipo y expresiones. Revalida inmediatamente antes de cada cambio y verifica su resultado. Si ya se retiraron, los omite.

Se usó `ALGORITHM=INPLACE, LOCK=NONE` y un límite de espera de metadatos de cinco segundos. Esto permite DML concurrente para la operación soportada, pero no elimina las breves necesidades de bloqueo de metadatos. Referencia: [MySQL 9.7, operaciones DDL online](https://dev.mysql.com/doc/refman/9.7/en/innodb-online-ddl-operations.html).

El DDL tiene confirmación implícita: cada cambio es independiente, no una transacción reversible mediante `ROLLBACK`. La evidencia conserva instrucciones `ADD INDEX` para reconstruir cada índice eliminado si fuera necesario. No se desactivaron las FK.

- [Evidencia aplicada: SQL, reversión y planes antes/después](../output/index_optimization_20261013_203329.json).
- [Verificación posterior de índices y FK](../output/index_optimization_verification_20261013.json).
- [Medición preliminar sin cambios](../output/index_optimization_20261013_203306.json).
- Validación del script: **9 pruebas aprobadas**, incluyendo rechazo de índices únicos, reemplazo ausente y diferencias de definición.

El script toma los cinco planes anteriores del archivo de auditoría y conserva sus filtros de octubre de 2026. Para otra fecha, revisar esos filtros antes de repetir. No se activaron registros lentos ni se alteraron parámetros globales del servidor.
