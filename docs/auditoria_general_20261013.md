# Auditoría general del backend y oportunidades de rendimiento

Fecha: 13 de octubre de 2026. Proyecto: FichaYa / control de asistencia.

La prioridad es corregir permisos y cálculos antes de acelerar los reportes. Se reprodujeron cuatro problemas con datos sintéticos: una desactivación permitida a un usuario de solo lectura, ausencias asignadas a un mes futuro, horas de jornada partidas calculadas en exceso y textos convertidos en fórmulas en el exportador Excel general. Las principales oportunidades de velocidad están en Vacaciones, Reportes de asistencia, Seguridad e Higiene y exportaciones compartidas.

## Alcance y resultados

Se inventariaron 458 declaraciones de rutas en 52 archivos de aplicación. Se analizaron sintácticamente 280 archivos Python, incluidas 90 unidades de pruebas, 156 plantillas Jinja y 11 archivos JavaScript de `static/js`, sin errores de sintaxis. El inventario de rutas no equivale a una prueba funcional de cada endpoint.

La revisión combina inspección de rutas, servicios, repositorios, configuración y recursos compartidos; pruebas existentes; y reproducciones aisladas. La revisión detallada se concentró en los hallazgos de mayor impacto. No se modificó código de negocio, no se desplegó y no se ejecutaron cambios de esquema ni escrituras contra la base real.

| Entorno de pruebas | Aprobadas | Fallidas | Omitidas | Duración |
|---|---:|---:|---:|---:|
| Python global, Flask 3.0.0 | 873 | 4 | 132 | 102,16 s |
| Entorno virtual del proyecto, Flask 3.1.2 | 876 | 1 | 132 | 86,18 s |

La ejecución del entorno virtual es la referencia. Ambos intérpretes locales son Python 3.14.2; el Dockerfile declara Python 3.12.13. Estas duraciones corresponden a tests, no a tiempos de navegación ni a un benchmark entre versiones.

Las 132 pruebas omitidas requieren integración o infraestructura no habilitada. Se desactivaron `RUN_DB_INTEGRATION`, `SH_TEST_DB_PORT` y `CARGA_TEST_DB_PORT`; las conexiones configuradas para las pruebas apuntaron a `127.0.0.1:1`. No se midieron latencias SQL reales, p95 de producción, concurrencia, consumo de memoria del servidor ni tiempos de navegador. No se verificó si las migraciones de índices están aplicadas en producción.

Evidencias locales:

- [Script reproducible sin conexión a la base](../scripts/audit_project_readonly.py).
- [Inventario, reproducciones y benchmark sintético](../output/audit_20261013_evidence.json).
- [Resultado completo de pytest en el entorno virtual](../output/audit_20261013_tests.xml).

## Hallazgos prioritarios

P1: corregir primero por integridad, permisos o riesgo de saturación. P2: optimizar o resolver en la siguiente etapa. P3: mejoras complementarias. Una oportunidad de rendimiento identificada en código no acredita por sí sola lentitud en producción.

### P1 Permiso de lectura permite una desactivación

**Comprobado con una petición simulada.** `GET /empleados/desactivar/123` devuelve 302 y llama a `set_activo(123, 0)` para un usuario activo con rol `consulta` y únicamente `empleados.ver=True`. La prueba mantuvo CSRF habilitado y sustituyó la escritura por un registro en memoria.

La ruta modifica datos mediante GET y `_action_for_current_request()` clasifica todos los GET como `ver`. Cuando el usuario no cumple el rol, `role_required` permite el acceso por ese permiso de lectura. El inventario detectó 16 rutas GET de activar/desactivar en Empleados, Empresas, Horarios, Tipos de evento de legajos, Puestos, Sectores, Sucursales y Usuarios. La reproducción funcional corresponde a Empleados; las demás requieren pruebas específicas de sus reglas.

**Corrección:** cambiar las mutaciones a POST con CSRF, exigir explícitamente la acción adecuada y comprobar el alcance de empresa sobre el registro afectado. No alcanza con ocultar el enlace. Criterio de aceptación: GET no modifica y un usuario de solo lectura recibe 403 al intentar la operación.

Evidencia: [rutas de empleados](../web/empleados/empleados_routes.py), líneas 439–452; [decoradores](../web/auth/decorators.py), líneas 145–173.

### P1 Asistencias cuenta el futuro como ausencia

**Comprobado.** Con un empleado activo, sin marcas y noviembre de 2026, el servicio devuelve 25 ausencias computables y 100 % de ausentismo aunque la fecha de esta auditoría es el 13 de octubre. Esto explica el porcentaje elevado observado al navegar al mes siguiente; es independiente del problema de colores corregido anteriormente.

El cálculo recorre todos los días laborables del mes sin fecha de corte. También usa el estado activo actual del empleado para un reporte histórico. Este segundo comportamiento puede alterar el pasado al desactivar a una persona y necesita una regla explícita de vigencia.

**Corrección:** separar calendario planificado de asistencia evaluable, incorporar fecha de corte local y estado “futuro/no evaluado”. Definir cuándo el día actual puede contarse como ausencia. Para períodos históricos, considerar altas y bajas en el período en lugar del estado actual solamente.

Evidencia: [servicio mensual](../services/asistencia_monthly_report_service.py), líneas 81–95 y 170–220.

### P1 Jornadas partidas suman horas no trabajadas

**Comprobado.** Las marcas 08:00 ingreso, 12:00 egreso, 16:00 ingreso y 20:00 egreso producen **12 horas**, aunque los dos tramos suman **8 horas**. Se toma el último egreso menos el primer ingreso, tanto en la planilla como en el detalle de jornada.

**Corrección:** sumar pares válidos de ingreso/egreso y definir tratamiento de marcas repetidas, faltantes y cruces de día. Reutilizar una sola función de cálculo para reportes, dashboards y exportaciones. Criterio de aceptación: el ejemplo produce 8 horas en todas las salidas.

Evidencia: [servicio mensual](../services/asistencia_monthly_report_service.py), líneas 176–185 y 225–236.

### P1 Textos exportados se interpretan como fórmulas

**Comprobado en el archivo generado, sin abrir Excel.** El exportador general recibe el texto `=1+1` y lo almacena en A4 con tipo `f` —fórmula— en lugar de texto. El problema alcanza los campos de texto controlables por usuarios que llegan a ese exportador; no se afirma que todos los exportadores particulares tengan el mismo problema.

**Corrección:** escribir explícitamente como texto los valores textuales y conservar como numéricos los valores numéricos. Aplicar una política equivalente a CSV. Criterio de aceptación: cadenas de entrada no se convierten en fórmulas al inspeccionar el libro generado.

Evidencia: [exportador general](../services/table_export_service.py), líneas 90–112 y 191–198; reproducción `excel_text` del JSON.

### P1 Exportaciones masivas ocupan los procesos web

**Comprobado en código; saturación no medida.** `EXPORT_PAGE_SIZE` vale 1.000.000. Los datos se materializan en listas y se construyen Excel/PDF completos en memoria durante la petición. Excel además aplica formato por celda y recorre columnas para ajustar sus anchos. Una exportación grande puede consumir memoria y mantener ocupado un proceso web.

El Dockerfile configura por defecto dos workers de Gunicorn y un timeout de 120 segundos. El worker síncrono procesa una solicitud a la vez; por tanto, dos exportaciones simultáneas pueden ocupar ambos workers si se usa esa configuración. [Diseño de Gunicorn](https://docs.gunicorn.org/en/stable/design.html?highlight=workers).

**Corrección:** imponer límites explícitos con un mensaje al usuario, exigir filtros para grandes períodos y generar las exportaciones grandes en un proceso separado. Para CSV, evaluar lectura por lotes y streaming; para Excel, escritura optimizada y límites de formato. Aumentar el timeout por sí solo no libera capacidad.

Evidencia: [panel_export_service.py](../services/panel_export_service.py), líneas 52, 86–93 y 644–653; [table_export_service.py](../services/table_export_service.py); [Dockerfile](../Dockerfile).

### P2 Vacaciones consulta por cada empleado

**Comprobado en código.** `_build_reporte_vacaciones` recorre empleados y llama a `calcular_resumen_vacaciones` individualmente. Esa función carga el empleado y sus entradas de cálculo desde repositorios. El número de consultas crece con la dotación; afecta la pantalla del reporte y sus exportaciones.

Ya existe `calcular_resumenes_vacaciones`, que obtiene los insumos por lotes, y se usa en el listado de Empleados. Es una oportunidad de reutilización concreta. Debe preservarse el tratamiento de empleados inactivos y errores que hoy muestra el reporte.

El listado general de Vacaciones además carga `get_all()` para el historial anterior, aunque los movimientos principales estén paginados. Ese historial se incorpora al HTML; conviene cargarlo cuando se despliega o paginarlo por separado.

Evidencia: [rutas de vacaciones](../web/vacaciones/vacaciones_routes.py), líneas 186–249 y 287; [servicio](../services/vacaciones_service.py), líneas 152–189; [listado de empleados](../web/empleados/empleados_routes.py), líneas 238–246.

### P2 Reportes de asistencia repiten consultas y recorridos

**Comprobado en código y con benchmark sintético de CPU.** Cada solicitud construye el informe actual completo y el informe anterior completo, aunque la solapa seleccionada no muestre la comparación. Las marcas se traen por empresa y luego se filtran por sucursal/sector en Python. El informe calcula todas las solapas y vuelve a ordenar las marcas para el detalle de jornada.

Dentro de cada empleado se recorre el conjunto completo de claves de marcas para encontrar sus fechas. Con N empleados y D fechas, esa parte escala aproximadamente como N² × D.

| Empleados simulados | Marcas | Mediana de 3 ejecuciones |
|---|---:|---:|
| 100 | 5.200 | 31,44 ms |
| 500 | 26.000 | 318,57 ms |
| 1.000 | 52.000 | 1.070,27 ms |

Mediciones en la PC local, Python del entorno virtual, sin SQL, HTTP ni renderizado. No son tiempos de producción ni una promesa de mejora.

**Corrección:** indexar fechas por empleado, calcular una vez los tramos diarios, consultar la comparación solo cuando haga falta y trasladar filtros a SQL. Elegir proyecciones y agregaciones según la solapa. Mantener reconciliación entre KPIs y detalle.

Hay además un límite silencioso de 20.000 justificaciones en el reporte, aplicado antes de algunos filtros de empresa/sector. Superarlo podría clasificar como ausencia una justificación omitida. Usar una consulta específica por alcance o recorrer todos los lotes necesarios.

Evidencia: [ruta mensual](../web/asistencias/asistencias_routes.py), líneas 569–664; [servicio mensual](../services/asistencia_monthly_report_service.py), línea 223; JSON `synthetic_cpu_benchmark`.

### P2 Seguridad e Higiene pagina después de cargar el período

**Comprobado en código.** El dashboard lee todos los eventos del período y todos sus participantes, calcula rankings y series en Python y recién entonces toma los 30 elementos visibles. El período admite hasta diez años. Las descripciones y conteos de fotos ya se limitan a la página visible: esa optimización debe conservarse.

**Corrección:** separar agregados SQL para indicadores y rankings de una consulta paginada para el listado; cargar personas solo de los eventos visibles. Respetar la diferencia entre cantidad de eventos y cantidad de participaciones, los filtros organizativos y el tratamiento de externos. No usar el total de filas visibles para calcular indicadores globales.

Evidencia: [dashboard de seguridad](../services/seguridad_dashboard_service.py), líneas 37–122.

### P2 Arranque con migraciones y tareas por worker

**Comprobado en configuración y código; incidencia concurrente no reproducida.** `create_app()` llama a `init_db()`, que comprueba y crea esquema/índices y ejecuta actualizaciones de justificaciones. Como el comando de Gunicorn no usa preload, cada worker inicializa la aplicación. Esto agrega trabajo al arranque y puede producir carreras entre la comprobación y creación de un índice cuando falta.

La misma factory inicia los schedulers de Trivia y Reintegros. La variable global `_scheduler` y `max_instances=1` coordinan dentro del proceso, no entre workers. Hay protecciones de idempotencia y bloqueos en algunas operaciones: el hallazgo es ejecución y trabajo duplicados potenciales, no una afirmación de premios o pagos duplicados.

**Corrección:** migraciones versionadas en una fase única de despliegue y un proceso dedicado para tareas programadas, manteniendo idempotencia. APScheduler documenta las limitaciones de coordinación entre procesos y la alternativa de un proceso dedicado. [Documentación de APScheduler 3](https://apscheduler.readthedocs.io/en/3.x/faq.html#how-do-i-share-a-single-job-store-among-one-or-more-worker-processes).

Evidencia: [app.py](../app.py), líneas 289 y 410–414; [extensions.py](../extensions.py); [trivia_scheduler.py](../utils/trivia_scheduler.py); [reintegro_scheduler.py](../utils/reintegro_scheduler.py).

### P2 Contadores de acceso en memoria por proceso

**Condicional a la configuración desplegada.** El limitador usa `memory://` si no se configura `RATELIMIT_STORAGE_URI`. Los límites de login entonces son por worker y se reinician con él. El código ya admite un almacenamiento compartido; no se inspeccionó la variable en producción.

**Corrección:** verificar el backend efectivo y, si hay varios workers, usar un almacenamiento compartido soportado. No aumentar procesos sin revisar conexiones SQL, tareas y limitadores.

Evidencia: [limiter.py](../utils/limiter.py), líneas 6–14; límites en [login web](../web/auth/web_auth_routes.py) y [login API](../routes/auth_routes.py).

### P2 Pruebas y entorno local no uniformes

**Comprobado.** El Python global no respeta las versiones fijadas. Los tres errores por asignar `request.max_content_length` desaparecen al ejecutar con el entorno virtual. La configuración de ese límite por petición fue incorporada en Flask 3.1. [API de Flask](https://flask.palletsprojects.com/en/stable/api/#flask.Request.max_content_length).

En el entorno correcto queda fallando `TestAppVersionPanelAcceso.test_listado_403_para_rol_no_admin`: espera 403 pero obtiene 500. El test simula `has_role` pero no la consulta de permisos usada como alternativa; termina en `RuntimeError: ORM no inicializado`. Es un problema de aislamiento de la prueba, no evidencia suficiente de un 500 en producción con base disponible.

**Corrección:** ejecutar y automatizar con el entorno fijado, completar los dobles de permisos del test y agregar un job con MySQL/MariaDB aislado para las 132 pruebas omitidas. Alinear también la versión de Python con la imagen de despliegue. No declarar la suite verde hasta resolver el fallo.

## Oportunidades complementarias

| Área | Observación | Próxima comprobación o mejora |
|---|---|---|
| Justificaciones | Los filtros de fechas usan `COALESCE` sobre columnas, aunque el arranque normaliza fechas | Verificar datos y EXPLAIN antes de cambiar el predicado; conservar solapamiento de rangos |
| Formularios y filtros | Varias pantallas cargan catálogos completos de empleados, sectores y sucursales | Buscar empleados del alcance mediante endpoint paginado y conservar selecciones; no compartir caché entre empresas |
| Horarios | El detalle estructurado lee bloques dentro del bucle de días | Consulta por lote de bloques; el número de días es pequeño, prioridad menor que Vacaciones |
| Trivia | Recordatorios consultan existencia y guardan por persona y tipo | Inserción por lote respetando claves únicas; evitar viajes repetidos a SQL |
| Presencia | Consulta cada 30 s por pestaña; ocultarla no cancela la cadena de consultas | Suspender refresco con la página oculta, reanudar al volver y medir carga con varios monitores |
| Notificaciones del panel | Carga asíncrona ya evita demorar la pantalla, pero realiza conteos separados | Medir número y tiempo de consultas; agrupar consultas cuando conserve filtros y permisos |
| Recursos visuales | `panel.css` pesa 128.118 bytes sin comprimir y se carga globalmente | Medir compresión y caché reales; separar estilos de módulos, versionar activos y revisar colisiones |
| Imagen de despliegue | `.dockerignore` no excluye `instance`, `output`, `tmp` ni logs locales | Revisar su contenido y excluir artefactos de auditoría y temporales del contexto Docker |
| Observabilidad | Existe `Server-Timing` de aplicación; métricas de SQL específicas para SKAP | Contador y tiempo SQL por petición en todos los módulos, p50/p95, errores y memoria; no registrar datos personales |

El endpoint de Presencia entrega nombres y estados sin autenticación por diseño del código. No se cambió ese contrato. Antes de publicar nuevas vistas equivalentes, confirmar si deben ser públicas, internas o llevar un token de pantalla. La revisión de aislamiento por empresa de las rutas heredadas sigue siendo necesaria; las rutas nuevas de EPP/Reintegros tienen controles explícitos de alcance que no están uniformados en todo el backend.

## Cobertura por grupos de módulos

La tabla resume inspección de código e inventario y ejecución de la suite disponible. No certifica ausencia de errores ni una velocidad medida de cada módulo.

| Módulos | Resultado y prioridad |
|---|---|
| Inicio y dashboard | Métricas, filtros, calendario y notificaciones inventariados; medir consultas agregadas y alcance |
| Asistencias, marcas y reporte mensual | P1 cálculos de futuro y jornada; P2 doble informe, recorridos y justificaciones truncadas |
| Presencia | Lectura por sucursal y refresco revisados; optimizar consultas de pestañas ocultas y revisar exposición pública |
| Empleados | Listado paginado y vacaciones por lote ya presentes; P1 mutaciones GET; reducir catálogos completos |
| Empresas y sucursales | P1 rutas GET de estado; revisar alcance de empresa y reutilización de catálogos |
| Sectores, puestos, localidades y organigrama | P1 rutas GET donde corresponda; medir tamaño de árboles y opciones de formularios |
| Horarios, asignaciones y excepciones | P1 GET de estado de horarios; listados de asignaciones cargan empleados completos; bloques por día con consultas adicionales |
| Vacaciones, compensatorios y francos | P2 reporte por empleado e historial heredado completo; conservar validaciones de saldo y habilitación |
| Justificaciones | Revisar costo de filtros por rango y coherencia con el reporte mensual; adjuntos tienen pruebas existentes |
| Legajos y tipos de evento | Carga por lote de adjuntos y reutilización del dashboard ya cubiertas por pruebas; P1 GET de tipos de evento |
| Adelantos y pedidos de mercadería | Listados, servicios y pruebas ejecutados; priorizar exportaciones compartidas y medición de filtros |
| Reintegros y viáticos | Historial SQL paginado y alcance explícito; revisar scheduler compartido; pruebas de integración omitidas |
| EPP y ropa | Historial paginado; catálogo no descarga el BLOB de imagen; pruebas de integración omitidas |
| Seguridad e Higiene, rankings y campeón | P2 dashboard completo en memoria; mantener consultas de fotos limitadas y alcance; integración omitida |
| Validación de carga e importaciones | Pruebas sin base pasan con Flask correcto; integración omitida; medir lotes e imágenes en entorno aislado |
| Feedback | Dashboard usa agregaciones y listados tienen filtros; medir JOIN, búsquedas por texto y condiciones de vencimiento |
| SKAP y matrices | Matrices consultan 26 filas para mostrar 25; conservar esa paginación y medir deserialización del contenido |
| KPIs sectoriales y premios | Pruebas unitarias/web disponibles ejecutadas; revisar exportaciones y catálogos completos antes de microoptimizar |
| Trivias | Cierres con transacciones y bloqueos; P2 scheduler por worker y recordatorios por empleado |
| Usuarios, roles y permisos | P1 clasificación GET como lectura; pruebas de autorización deben cubrir ruta más método más acción |
| Configuración, auditoría y versión de app | Exportaciones compartidas; un test de permisos de versión necesita aislamiento actualizado |
| Estadísticas móviles y calificaciones | Inventario de rutas y consultas; medir agregaciones y tamaños reales, sin cuello de botella específico demostrado |
| API móvil, externa, QR y medios | Suite disponible ejecutada; conservar controles JWT, validación QR y privacidad de adjuntos; medir serialización y transporte |
| Infraestructura compartida | P1 exportaciones; P2 arranque, schedulers, limitador, observabilidad y uniformidad de entorno |

## Orden de implementación

1. **Integridad y permisos:** convertir mutaciones GET a POST, comprobar permisos explícitos, corregir ausencias futuras y sumar tramos de jornada, proteger exportaciones frente a fórmulas.
2. **Velocidad con cambios acotados:** reutilizar vacaciones por lote, indexar fechas de marcas, evitar construir el mes anterior en solapas que no lo necesitan, paginar el historial heredado.
3. **Escalabilidad:** agregar indicadores de seguridad en SQL, limitar/encolar exportaciones grandes, sacar migraciones y schedulers de los workers web.
4. **Validación del despliegue:** suite con entorno fijado y base aislada; mediciones desde el servidor con datos representativos, luego prueba de concurrencia controlada.

Para cada módulo medir tiempo total, tiempo y cantidad de consultas, filas leídas/devueltas, tamaño de respuesta, memoria y errores. Comparar p50/p95 con idéntico alcance y datos antes y después. Empezar por Vacaciones, Reportes de asistencia, Seguridad y exportaciones, y continuar con los módulos restantes. No hay una estimación responsable de porcentaje de aceleración global sin esa medición.

Como antecedente, [la revisión del 6 de octubre](rendimiento_seguridad_20261006.md) documenta latencia elevada entre la PC y la base y optimizaciones ya aplicadas. Es evidencia histórica; no se presenta como medición actual ni como tiempo de producción.
