# Rendimiento y seguridad — 6 de octubre de 2026

## Mediciones reales

Medidas desde la PC de desarrollo hacia la base configurada, no desde el proceso
de Railway. Cinco muestras por consulta sobre una misma conexión. Sin pruebas de
carga concurrentes ni escrituras de datos de negocio.

| Operación | Resultado |
|---|---:|
| Apertura de una conexión nueva | 1.728 ms |
| Consulta mínima `SELECT 1`, mediana | 241 ms |
| Resumen mensual de asistencias, mediana | 236 ms |
| Resumen mensual de justificaciones, mediana | 234 ms |
| Historial de seguridad, 30 filas, mediana inicial | 245 ms |
| Servicio completo de dashboard, antes, mediana de 3 muestras | 2.799 ms |
| Servicio completo de dashboard, después, mediana de 3 muestras | 2.536 ms |

El servicio del dashboard mejoró aproximadamente 9,4 % en esta muestra. Se
alternó el orden de ejecución, con pool precalentado, 267 eventos y 30 filas
visibles. Los resultados completos coincidieron en las tres comparaciones,
excluyendo únicamente la hora de actualización. No es el tiempo total de página
ni garantiza la misma diferencia en producción.

`EXPLAIN ANALYZE` posterior: historial ~1,22 ms; conteo de asistencias ~1,58 ms;
importaciones pendientes ~0,081 ms dentro de MySQL. Son consultas representativas,
no percentiles de toda la aplicación. La diferencia con los tiempos cliente
muestra que la comunicación remota pesa más que el procesamiento SQL observado.

## Índices aplicados a la base conectada

- `sh_eventos`: `ix_sh_estado_fecha (empresa_id, estado, fecha_evento, id, tipo)`.
- `sh_fotos`: `ix_sh_fotos_activas (evento_id, activo)`.
- `sh_import_filas`: `ix_sh_import_pendientes (importacion_id, evento_id)`.

Creación con `ALGORITHM=INPLACE, LOCK=NONE`, espera de metadata lock de cinco
segundos y sin alternativa bloqueante. No se eliminaron índices existentes.
Se detectan índices equivalentes por columnas, prefijos e invisibilidad.
La segunda ejecución con `--apply` reconoció los tres índices y no los recreó.

La consulta de pendientes usa el nuevo índice y queda cubierta. Con los 267
eventos actuales, MySQL todavía prefiere índices anteriores para las consultas
de historial y comparación anual. No se fuerza un índice ni se atribuye a estos
índices una reducción grande de latencia que las mediciones no demuestran.
Asistencias y justificaciones ya utilizan sus índices de fecha existentes.

Auditar o aplicar en otro entorno:

```powershell
python scripts/migrate_20261006_01_panel_performance.py --output instance/auditoria_nueva
python scripts/migrate_20261006_01_panel_performance.py --apply --output instance/aplicacion_nueva
```

Cada directorio de salida debe ser nuevo. Incluye definiciones anteriores,
resultados y SQL de reversión solo de los índices creados por esa ejecución.
DDL no es transaccional: revisar `result.json` ante un fallo parcial.

Evidencias privadas: `instance/performance_20261006_applied/`, incluidos
`result.json`, `server_plans.json` y `dashboard_final_comparison.json`.

## Cambios de aplicación

- Dashboard: descripciones y conteos de fotos solo para los 30 eventos visibles;
  los totales, rankings y series siguen usando todos los eventos del alcance.
  Configuración y pendientes se leen juntos para no aumentar viajes a la base.
- Fotos de Seguridad e Higiene: autorización y lectura en una consulta; se evita
  cargar el detalle, participantes, auditoría y acciones por cada imagen.
- Detalle, ranking y catálogos: se dejan de pedir listas que esas vistas no usan.
- Lecturas de Carga y Seguridad: se omite el COMMIT redundante; al devolver la
  conexión al pool se reinicia su transacción. Las escrituras conservan commit
  y rollback. No se almacenan datos privados en cachés compartidas.
- El alcance de empresa de Carga/Seguridad reutiliza el usuario consultado por
  los permisos durante la misma petición, sin prolongar permisos entre pedidos.
- Descargas de adjuntos: se elimina `CREATE TABLE IF NOT EXISTS` en cada lectura.
  La tabla se crea al guardar adjuntos y debe existir para leerlos.

## Seguridad

- Un usuario inexistente del panel ya no puede heredar roles de un empleado que
  casualmente tenga el mismo ID. La caché de usuarios inexistentes dura solamente
  una petición; una petición nueva vuelve a consultar.
- Adjuntos de legajos y evidencias de feedback exigen permiso del módulo,
  usuario activo y empresa coincidente. El administrador mantiene su alcance
  global. En legajos también se comprueba la empresa del evento padre.
- Documentos privados y respuestas autenticadas: `Cache-Control: private,
  no-store`. Recursos estáticos conservan su caché condicional.
- CSP básica contra objetos incrustados, cambio de base URL y enmarcado por otros
  sitios. No es todavía una CSP estricta de scripts con nonces.
- JWT exige expiración; el guard móvil rechaza IDs inválidos y tokens de QR como
  credenciales de sesión. Los tokens emitidos normalmente ya incluyen `exp`.
- Debugger local deshabilitado por defecto. Solo se habilita explícitamente con
  `APP_ENV=development` y `FLASK_DEBUG=1`; no usarlo en un servicio publicado.
- Tamaño global de petición limitado a 128 MiB, configurable por
  `MAX_REQUEST_BYTES`. Seguridad conserva su límite específico de 27 MiB.
- Fotos de perfil: lectura limitada al máximo configurado más un byte, antes de
  decodificar la imagen, para rechazar archivos enormes sin leerlos completos.
- Limitador admite `RATELIMIT_STORAGE_URI` para almacenamiento compartido. No se
  configuró Redis: en memoria, los contadores siguen siendo por proceso.
- Errores HTTP de Carga/Seguridad móvil devuelven JSON.

## Alcance y despliegue

Validación: 299 pruebas aprobadas en dos ejecuciones finales, incluyendo la API
móvil, QR, autenticación, permisos, adjuntos, paginación, Carga y Seguridad.
Las nueve pruebas de Carga omitidas en la primera ejecución se ejecutaron y
aprobaron en la segunda contra MariaDB aislado. Se verificaron también sintaxis
Python y diferencias sin errores de whitespace.

Los índices ya están aplicados. El código requiere desplegar/reiniciar el backend.
No se rotaron secretos, no se modificó infraestructura y no se publicó una nueva
versión de Flutter. Los contratos existentes conservan sus respuestas normales.

La revisión cubrió infraestructura compartida y consultas de los módulos citados;
no certifica la ausencia de vulnerabilidades en todas las rutas. Las fotos de
perfil por DNI siguen siendo públicas por el contrato existente: privatizarlas
requiere adaptar sus consumidores. El aislamiento completo de empresas en módulos
heredados y una auditoría de dependencias requieren una revisión adicional.

Para medir la experiencia de producción, ejecutar las mismas pruebas desde el
entorno del backend y registrar tiempos de página y percentiles con concurrencia.
La latencia PC→base no permite deducir la latencia backend→base. Verificar esa
ruta de red antes de aumentar recursos o cambiar el tamaño del pool.
