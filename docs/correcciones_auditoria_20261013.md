# Correcciones de la auditoría general

Cambios preparados en el código local el 13 de octubre de 2026. No se desplegaron ni se modificó la base de producción.

## Integridad y permisos

- Las 16 rutas de activar/desactivar aceptan únicamente POST, con CSRF y permiso `aprobar` del módulo. En registros con empresa, un usuario no administrador sólo puede modificar su propia empresa. Los tipos de eventos de legajo son un catálogo global sin columna de empresa.
- El reporte mensual evalúa ausencias hasta ayer, según la fecha de Argentina. Hoy y los días futuros figuran sin evaluar, con denominador cero cuando corresponde; tampoco muestran una mejora porcentual ficticia contra el mes anterior. El calendario futuro sigue siendo editable.
- La vigencia laboral respeta fecha de ingreso y baja. Un empleado inactivo con baja registrada sigue apareciendo en su período histórico; sin fecha de baja no se inventa una vigencia.
- Las horas se calculan sumando pares de ingreso/egreso. Las marcas duplicadas o incompletas se señalan. No se inventa un cierre nocturno entre días: una entrada sin salida queda incompleta.
- Los Excel generales y los exportadores particulares de datos conservan texto como texto. Los CSV neutralizan prefijos de fórmula, conservando números reales. El PDF general escapa contenido textual antes de pasarlo al motor de composición.
- La exportación general exige permiso `exportar`, sin depender de inspeccionar internamente un decorador de roles.

## Consultas y cargas

- Asistencia: un cálculo diario compartido por planilla y jornada, sin recorrer todas las claves de marcas por cada empleado. La comparación anterior se consulta sólo en Resumen. Los filtros de sucursal/sector llegan a SQL. Las justificaciones aprobadas usan una consulta específica por alcance, sin el recorte de 20.000 filas.
- Vacaciones: cálculo de saldos por lote, conservando errores por empleado. El historial aprobado reutiliza el listado paginado y sus filtros; deja de descargar otro historial completo oculto dentro del HTML.
- Seguridad e Higiene: indicadores, series, categorías y rankings agregados en SQL. Sólo se leen los 30 eventos de la página y sus participantes. Se conserva el alcance organizativo sobre una misma persona y la separación de participantes externos.
- Horarios: bloques de todos los días en una consulta, sin una consulta adicional por día.
- Trivia: recordatorios por lotes de 500, en una transacción; la clave única de la base evita duplicados.
- Notificaciones del panel: cuatro conteos en una consulta. Los errores SQL no se transforman silenciosamente en un cero.
- Presencia: no programa nuevas consultas mientras la pestaña está oculta; actualiza al volver.
- Panel: CSS mensual separado, versiones de archivos CSS/JS para caché y gzip de recursos estáticos. El HTML y las respuestas privadas no se comprimen mediante este mecanismo.

## Exportaciones

El exportador general admite hasta 10.000 registros en Excel y 2.000 en PDF. Solicita una fila adicional o revisa el total del repositorio para rechazar el exceso con HTTP 422 y un mensaje de filtros, sin presentar un archivo parcial como completo. No se habilitaron exportaciones ilimitadas ni una cola de trabajos masivos: para superar estos límites se debe dividir la consulta mediante filtros.

Se corrigieron además cinco incompatibilidades de argumentos que podían causar HTTP 500: motivos y clientes de Feedback, Adelantos, Pedidos de mercadería y Concursos. Se incorporaron filtros organizativos faltantes en esas exportaciones y en Vacaciones. El historial QR conserva su límite de pantalla pero permite al exportador detectar el exceso del límite de descarga. Una prueba recorre los 35 cargadores del panel y valida sus llamadas contra las firmas reales de los repositorios.

## Arranque y operación

`init_db()` inicializa el ORM y ya no ejecuta DDL. `python scripts/bootstrap_schema.py` aplica una vez la compatibilidad que antes ejecutaba cada worker, registra su versión y usa un bloqueo de base de datos. No sustituye las migraciones funcionales históricas que ya requiere la aplicación.

El contenedor ejecuta `scripts/start_server.py`: bootstrap, un proceso de scheduler y Gunicorn. El scheduler elige una instancia mediante un bloqueo de la base; las demás esperan. Si pierde la conexión propietaria, el proceso falla y el supervisor detiene los hijos para que el hosting los reinicie. `SCHEDULER_IN_WEB=0` debe mantenerse en producción.

Para dos o más workers se debe configurar `RATELIMIT_STORAGE_URI` con Redis compartido y reinstalar `requirements.txt`. El entrypoint rechaza varios workers con `memory://`. Sin Redis usa un worker; esa alternativa requiere una sola réplica. Ver [.env.deploy.example](../.env.deploy.example). No se aprovisionó Redis ni se inspeccionaron secretos del hosting.

En una ejecución local directa, ejecutar el bootstrap cuando corresponda y mantener `python scripts/run_scheduler.py` como proceso separado de `python app.py`. No iniciar nuevamente schedulers dentro de cada worker.

Cada solicitud registra cantidad de consultas y tiempo DBAPI acumulado, junto con el tiempo total. `Server-Timing` expone la duración agregada; no se registran SQL, parámetros ni resultados. Esta métrica permite identificar los siguientes módulos que requieran optimización con datos reales.

El Dockerfile excluye datos locales, salidas de pruebas y logs. Se agregó CI con Python 3.12.13 y MariaDB aislada para las suites de Seguridad y Carga.

## Validación y límites

La suite completa terminó con **1.063 pruebas aprobadas, cero fallidas y cuatro omitidas**, en 171,45 segundos. Tras el ajuste final del cierre de schedulers se ejecutaron tres pruebas específicas adicionales, todas aprobadas. `git diff --check` no detectó problemas.

El benchmark sintético de CPU, sin SQL ni navegador y ejecutado sin otras pruebas en paralelo, dio estas medianas de tres repeticiones:

| Empleados | Auditoría original | Después |
|---|---:|---:|
| 100 | 31,44 ms | 22,49 ms |
| 500 | 318,57 ms | 115,20 ms |
| 1.000 | 1.070,27 ms | 243,77 ms |

Para 1.000 empleados se redujo el tiempo de cálculo aproximadamente un 77 %. No representa una medición del sistema completo ni una promesa de velocidad en producción.

Las pruebas utilizan una instancia MariaDB local separada en el puerto 33319, con bases temporales identificadas por UUID. No usan la base configurada en `.env`. Las cuatro pruebas heredadas que dependen de una base completa permanecen deshabilitadas.

Las reproducciones comprueban GET 405 sin escritura, cero ausencias para un mes futuro, ocho horas para 08–12/16–20 y texto literal en Excel. También hay pruebas de aislamiento por empresa, CSRF, límites de exportación, compresión, métricas, migración aplicada una vez, recordatorios idempotentes y más de 20.000 justificaciones.

La revisión sintáctica cubre Python, las 156 plantillas Jinja y los JavaScript del panel. La ejecución del contenedor con Python 3.12 queda para CI: el motor Docker local devolvió un error 500; el Python del entorno virtual local es 3.14.2. No se realizó una nueva verificación visual de navegador ni medición de latencia/concurrencia de producción.

Las oportunidades exploratorias del informe original —buscadores remotos para todos los catálogos, eliminación de compatibilidad `COALESCE`, política de acceso a Presencia y medición p95 de cada módulo— requieren datos o decisiones adicionales. No se presentan como defectos ya comprobados ni como mejoras de velocidad medidas.

Evidencias: [suite completa](../output/correcciones_20261013_final.xml), [reproducciones y benchmark sintético](../output/correcciones_20261013_evidence.json), [auditoría original](auditoria_general_20261013.md).
