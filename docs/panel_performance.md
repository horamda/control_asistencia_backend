# Rendimiento del panel: cambios y verificacion

- Las alertas se solicitan desde `/panel/notificaciones` despues de mostrar el documento.
  El endpoint valida el usuario activo y su rol en la base; cache de sesion por usuario,
  empresa y rol durante 30 segundos. No se comparten respuestas por cache HTTP.
  Un error muestra reintento sin impedir usar el panel.
- SKAP administrativo pagina 25 filas (+1 para detectar siguiente), con orden estable
  y filtro de rol en SQL. La API movil conserva su listado completo y permisos.
- Las lecturas SKAP devuelven la conexion al pool sin COMMIT redundante.
  Las escrituras conservan commit/rollback transaccional.
- Se agregan `Server-Timing: app` y `skap_db`, y tiempos/cantidad de lecturas SKAP
  al registro de requests. No incluyen SQL ni valores personales.

Comparacion local contra la base configurada, misma consulta de 26 evaluaciones,
con conexion reutilizada, tres repeticiones intercaladas:

| Lectura | Antes (ms) | Despues (ms) |
|---|---:|---:|
| 1 | 1268 | 1000 |
| 2 | 1477 | 1006 |
| 3 | 1673 | 1256 |

Promedio: 1473 a 1087 ms (26 % menos). No es una medicion de pagina completa
ni un benchmark de produccion. La conexion inicial sigue teniendo latencia.
Evidencia privada: `instance/skap_revision/performance_comparison.json`.

Validacion: 20 tests de SKAP, permisos y alertas; sintaxis Python/JavaScript.
Pendiente tras despliegue: medir TTFB frio/caliente y percentiles con concurrencia,
comparar tiempo SQL vs pagina, verificar region de app/base e indices mediante
EXPLAIN antes de cambiar infraestructura o cantidad de workers. No se modificaron
recursos, configuracion de produccion ni indices en esta etapa.

## Extension conservadora a otros modulos

Se evita COUNT en la primera pagina cuando trae menos filas que la capacidad
solicitada, en 13 listados: empleados, sectores, justificaciones, marcas de
asistencia (administracion y empleado), adelantos (ambos), pedidos (ambos),
vacaciones (periodos personales y movimientos) y legajos (tipos y eventos).
Una pagina completa, una pagina posterior o un tamano no positivo mantienen
el conteo previo. Feedback omite la consulta de filas si el conteo es cero.
No se introducen caches de datos personales ni cambios en contratos o escrituras.
La mejora elimina una consulta en esos casos; no promete acelerar todos los
listados ni reemplaza la medicion de latencia en produccion.
Verificacion adicional: suites de vistas/repositorios (48 y 161 pruebas aprobadas) y 66 casos de paginacion/consulta vacia, con solapamiento entre suites.

## Limpieza de indices aplicada el 2026-09-20

Se retiraron exclusivamente tres indices no unicos con duplicado exacto visible:

| Tabla | Retirado | Conservado |
|---|---|---|
| asistencias | idx_asis_empleado_fecha | idx_asistencias_empleado_fecha |
| asistencias | idx_asis_empresa_fecha | idx_asistencias_empresa_fecha |
| legajo_eventos | fk_legajo_eventos_justificacion (indice) | idx_legajo_eventos_justificacion |

Las claves foraneas fueron comparadas antes/despues y permanecen identicas,
incluida la restriccion fk_legajo_eventos_justificacion. No se retiraron constraints.
DDL con ALGORITHM=INPLACE, LOCK=NONE y lock_wait_timeout=5; sin alternativa bloqueante.
Script reproducible: scripts/migrate_20260920_01_duplicate_indexes.py (vista previa
por defecto; --apply ejecuta). Requiere directorio de reporte nuevo.
Respaldo de definiciones, resultado por operacion y SQL de reversion en
instance/skap_revision/index_cleanup_applied/. DDL no es transaccional: consultar
result.json antes de ejecutar rollback.sql si hubiese una aplicacion parcial.

Se corrigieron los nombres exigidos por extensions.REQUIRED_INDEXES para no
recrear los duplicados al iniciar. Debe desplegarse esa correccion: un reinicio
del backend anterior puede recrear los dos indices de asistencias.

EXPLAIN ANALYZE posterior: lectura personal de marcas ~0.61 ms, lectura de
asistencias por empresa ~1.22 ms dentro del servidor, con indices. No representan
latencia de red ni tiempos completos del panel. Performance Schema no devolvio
muestras de SELECT para este esquema durante la revision; no se habilito logging
global ni se cambiaron parametros de produccion. Para el seguimiento del panel
quedan las mediciones Server-Timing y logs preparadas en el backend.

## Renderizado del panel

Las fuentes de Google se cargan sin bloquear la hoja principal, con alternativa
sin JavaScript y fuentes locales de respaldo. panel.js usa defer. Los controles
de menu/filtros reaccionan al cruce de sus puntos de corte mediante matchMedia,
en lugar de repetir escrituras del DOM en cada evento resize. Las fotos de
listados de empleados y legajos usan decoding=async junto con loading=lazy.
Se respetan preferencias de movimiento reducido para los controles del panel.

Son ajustes de presentacion; no modifican datos ni contratos. No se ha medido
una mejora de FCP/LCP/CLS en produccion: requiere desplegar y comparar en navegador.
