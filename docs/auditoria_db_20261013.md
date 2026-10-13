# Auditoría de la base real — 13/10/2026

## Resultado y alcance

Se consultó la base `railway` configurada para este proyecto, con transacciones de solo lectura. El servidor informó MySQL **9.7.2**. La ventana principal fue **20:20–20:27 UTC / 17:20–17:27 Argentina**. No se modificaron registros, índices, restricciones ni configuración global.

Hay **111 tablas InnoDB**, todas con clave primaria, **49.775 filas** sumando los conteos por tabla y **32,91 MiB** asignados a datos e índices según `information_schema`. La suma de filas combina entidades diferentes; no representa personas ni operaciones únicas. Los conteos se hicieron en transacciones cortas separadas, no en una instantánea única de toda la base.

Se conservaron **416 resultados de consultas**: 382 del relevamiento principal, 30 de planes/comprobaciones y 4 de seguimiento. Además, se midieron cinco ejecuciones de `SELECT 1`. No hubo errores en las consultas registradas. El número de resultados no incluye instrucciones de sesión/transacción ni consultas repetidas bajo una misma clave de evidencia.

La integridad referencial comprobada no presentó huérfanos. Los principales pendientes son **fechas de baja incompletas, conciliación de asistencias, observabilidad del rendimiento y verificación de recuperación ante pérdida de datos**. El tamaño observado no justifica por sí solo ampliar recursos.

## Hallazgos y acciones propuestas

| Prioridad | Evidencia | Impacto y siguiente acción |
|---|---|---|
| Alta | **32 empleados inactivos, todos sin `fecha_baja`**; 96 empleados en total, 64 activos; ninguno sin fecha de ingreso. | No puede reconstruirse la fecha de salida de la dotación histórica a partir de este campo. Validar si cada inactivación representa una baja laboral y completar la fecha con documentación; no inferirla de la última fichada. Revisar la obligatoriedad del campo en el flujo de bajas. |
| Alta | En 4.265 asistencias anteriores al 13/10, **825 tienen entrada sin salida** y **7 salida sin entrada**. | Afectan cálculos de duración y controles de asistencia. Revisar por empleado y ciclo con el responsable operativo antes de corregir datos. No son prueba por sí solas de corrupción técnica. |
| Alta | De esas 825 asistencias sin salida, **29 tienen alguna marca de egreso para el mismo empleado y día**. | Conciliar ambas fuentes y la vinculación por `asistencia_id`. La coincidencia por día no demuestra que el egreso pertenezca al mismo ciclo. No completar automáticamente las 29 salidas. |
| Alta | `slow_query_log=OFF`, `performance_schema=OFF`, `long_query_time=10`. | No hay evidencia histórica suficiente para ordenar las consultas por costo real. Preparar observabilidad y medir rutas de aplicación bajo carga representativa; evaluar costo y compatibilidad antes de cambiar parámetros del servidor. |
| Alta, verificación pendiente | `log_bin=OFF`; no se inspeccionaron respaldos externos ni pruebas de restauración. | No se pudo acreditar una estrategia de recuperación. Verificar en Railway frecuencia, retención, última copia correcta y restauración en una base aislada. La ausencia de binlog no demuestra ausencia de backups del proveedor. |
| Media | **Tres pares de índices con las mismas columnas y unicidad**, detallados abajo. | Posible costo de mantenimiento innecesario. Preparar una migración que conserve los índices requeridos por restricciones y consultas; validar primero fuera de producción. No se eliminó ninguno. |
| Media | `require_secure_transport=OFF`; la conexión de la auditoría sí usó `TLS_AES_128_GCM_SHA256`. | El servidor no exige transporte seguro globalmente. Verificar TLS y validación de certificados en todos los clientes antes de endurecer la configuración. No se comprobó aquí la configuración TLS de cada cliente. |

La revisión de fechas de baja anteriores al ingreso no puede concluir que todas sean válidas: la agregación devolvió `NULL` por falta de fechas comparables, no un cero demostrado.

### Índices con definición repetida

| Tabla | Columnas | Nombres |
|---|---|---|
| `empleado_excepciones` | `empresa_id, fecha` | `idx_ee_empresa_fecha`, `idx_ex_emp_empresa_fecha` |
| `empleado_horarios` | `empleado_id, fecha_hasta` | `idx_eh_actual`, `idx_empleado_horarios_vigente` |
| `empleado_horarios` | `empleado_id, fecha_desde, fecha_hasta` | `idx_eh_empleado_rango`, `idx_empleado_fechas` |

También existen restricciones repetidas sobre las referencias de `empleado_horarios.empleado_id` y `empleado_horarios.horario_id`. Antes de consolidarlas falta contrastar sus reglas de actualización/eliminación. Otros índices comparten prefijos; compartir un prefijo no basta para decidir que son prescindibles.

## Comprobaciones satisfactorias y excepciones interpretadas

- **178 restricciones FK declaradas**, cubiertas mediante 170 verificaciones de relaciones simples distintas y 6 compuestas. Dos restricciones simples repiten relaciones ya verificadas. No se encontraron huérfanos en estas comprobaciones.
- **46 verificaciones adicionales de referencias inferidas** por nombre de columna. Las únicas coincidencias aparentes fueron los 26 días no laborables con ámbito global: el código usa `(empresa_id, sucursal_id, sector_id)=(0,0,0)` como “todos”. El seguimiento confirmó 26 ámbitos globales y cero referencias inválidas fuera del valor `0`. No son huérfanos.
- **29 tablas** con `empresa_id` y `empleado_id`: cero diferencias entre la empresa del registro y la empresa actual del empleado. Esto no sustituye una auditoría completa de autorizaciones ni reconstruye traslados históricos.
- Cero diferencias de empresa entre empleados y sus sucursales, sectores o puestos. Sin nombres, apellidos, DNI o legajos vacíos; sin activos carentes de sucursal o sector.
- Sin grupos duplicados en DNI por empresa, legajo por empresa, nombre de usuario ni marcas por `(empleado_id, fecha, hora, accion)`.
- **174 grupos empleado/día con dos asistencias**, compatibles con múltiples ciclos diarios. `repositories/asistencia_repository.py` contempla crear una nueva asistencia después de cerrar el ciclo anterior. No se clasifican como duplicados indebidos ni se recomienda una restricción única empleado/día.
- Cero asignaciones de horario solapadas; cero rangos invertidos en las cinco tablas comprobadas: `empleado_horarios`, `justificaciones`, `legajo_eventos`, `vacaciones`, `vacaciones_movimientos`. Los límites nulos quedan fuera de la comparación de rangos invertidos.
- Cero fechas futuras respecto del día argentino en asistencias, marcas y eventos de Seguridad e Higiene. Asistencias y marcas llegan al 13/10; Seguridad e Higiene al 07/10. Esta última fecha no demuestra retraso de carga sin un compromiso de actualización definido.

## Rendimiento observado

Se analizaron **cinco planes `EXPLAIN`**, sin ejecutar `EXPLAIN ANALYZE`. Son estimaciones para filtros concretos de empresa 1 y fechas documentadas en el SQL, no tiempos medidos ni cobertura de todos los módulos.

| Consulta | Observación del plan |
|---|---|
| Marcas mensuales | Las ramas de la vista filtran por índices de empresa/fecha; las búsquedas de marcas usan empleado/fecha. La unión se materializa y ordena. Medir con rangos grandes antes de rediseñar la vista. |
| Justificaciones | Recorre las 13 filas de la tabla y busca al empleado por PK. Con este volumen no prueba un problema; reevaluar el filtro `COALESCE` si crece. |
| Seguridad e Higiene | Usa `ix_sh_estado_fecha`, recorrido inverso y límite de 30 registros. |
| Vacaciones aprobadas | Usa `idx_vac_mov_tipo_estado` y aplica filtros restantes; estima 42 filas antes del filtro. |
| Asistencias paginadas | Usa `idx_asistencias_empresa_fecha`, recorrido inverso y límite de 50. |

El buffer pool está configurado en **1 GiB**. Los contadores acumulados registraron 2.361 lecturas físicas sobre 51.993.410 solicitudes al buffer pool (aproximadamente 99,995 % de aciertos), máximo de 20 conexiones frente a un límite de 151 y 13 esperas de bloqueo que acumularon 4.611 ms. Corresponden a unos 8,4 días de uptime; no describen un pico específico ni descartan lentitud puntual. En la consulta a `INNODB_TRX` no había transacciones activas. Con `performance_schema` apagado, sus tablas vacías no acreditan ausencia de esperas o errores.

Cinco `SELECT 1`, midiendo solamente ejecución y lectura desde esta PC al proxy configurado, tuvieron una mediana de **247,32 ms**. Incluyen red y servidor. No representan la latencia desde el servidor de la aplicación ni el tiempo interno de una consulta. Los demás campos `elapsed_ms` también incluyen el inicio de transacción y no deben compararse como tiempos SQL puros. Esta medición justifica revisar la cantidad de viajes a la base y medir desde el entorno desplegado; no atribuye por sí sola la lentitud de la aplicación a Railway.

### Volúmenes comprobados

| Tabla | Filas exactas al consultar |
|---|---:|
| `empleados` | 96 |
| `asistencias` | 4.303 |
| `asistencia_marcas` | 7.108 |
| `mobile_sesiones` | 5.948 |
| `sh_eventos` | 275 |

Las tablas de adjuntos y fotos están entre las de mayor asignación de espacio. Con 32,91 MiB totales no se acredita una urgencia de mover archivos ni purgar registros. Una política de retención debe considerar primero requisitos operativos y respaldos.

## Evidencia y reproducción

Fuente primaria: servidor configurado mediante `db._load_db_settings()`, sin inicializar la aplicación ni ejecutar migraciones. Se utilizó un límite de sesión de 5 segundos por `SELECT`, lecturas agregadas y consultas de metadatos. Los archivos no contienen filas personales, contraseñas ni tokens de sesión.

- [Evidencia principal: SQL, resultados y fechas](../output/db_audit_20261013.json).
- [Planes y comprobaciones complementarias](../output/db_audit_plans_20261013.json).
- [Seguimiento de ámbitos globales, asistencias y latencia](../output/db_audit_followup_20261013.json).
- Scripts reproducibles: [principal](../scripts/audit_database_readonly.py), [planes](../scripts/audit_database_plans.py), [seguimiento](../scripts/audit_database_followup.py).

Los scripts conservan las consultas exactas y sus resultados como alternativa a un notebook. Para repetir, ejecutar desde el backend con el Python del entorno virtual, primero el principal y después planes/seguimiento. Requieren acceso autorizado a la base configurada. Los nombres de salida están fijados a esta fecha: copiar la evidencia antes de repetir para conservar este corte. Los planes tienen fechas explícitas de octubre de 2026; actualizarlas si cambia el período de análisis.

## Límites y orden de trabajo

No se validaron backups del proveedor, restauraciones, permisos de todas las cuentas, cifrado en reposo, equivalencia completa entre migraciones y esquema, calidad de todos los campos de las 111 tablas, ni rendimiento extremo a extremo de cada módulo. No se ejecutaron pruebas de carga en producción. Tampoco se verificó que los cambios locales de la auditoría anterior estén desplegados.

1. Acreditar backup/restauración y definir observabilidad de consultas.
2. Revisar las 32 inactivaciones sin fecha y conciliar asistencias incompletas con sus ciclos y marcas, manteniendo trazabilidad.
3. Preparar y probar la consolidación de índices/restricciones repetidos.
4. Medir las rutas más usadas desde el servidor desplegado, antes y después de las optimizaciones locales, y priorizar según tiempos y volumen reales.

Esta auditoría deja evidencia y acciones concretas; **no aplicó correcciones sobre los datos reales**.
