# Change log

### 1.24.0 (2026-07-14)
- Justificaciones requieren `fecha_desde`, `fecha_hasta` y `motivo` al crear.
- Web y Flutter admiten hasta 10 fotos o PDFs por justificacion.
- Todas las altas quedan inicialmente en estado `pendiente`.
- Nuevo `DELETE /me/justificaciones/{id}/adjuntos/{adjunto_id}` para quitar
  evidencias individuales mientras la justificacion siga pendiente.
- Si falla el guardado de evidencias durante el alta, el backend revierte la
  justificacion para evitar registros parciales.

### 1.23.1 (2026-07-14)
- Se explicita el contrato de busqueda de clientes para cargar feedback:
  - `q` busca por nombre del negocio (`nombre_fantasia`), razon social,
    direccion (`domicilio`) y codigo, ademas de otros datos del cliente.
  - Se documentan coincidencia parcial, busqueda de varias palabras, prioridad
    de resultados y presentacion recomendada para Flutter.
- OpenAPI corrige `per_page` maximo a 200, elimina una descripcion duplicada de
  `q` y agrega un ejemplo de busqueda por direccion.
- Sin cambios de comportamiento ni ruptura de compatibilidad.

### 1.23.0 (2026-07-14)
- Pedidos de mercaderia ahora admiten cantidades mixtas por articulo:
  - `cantidad_bultos`: bultos completos, entero mayor o igual a cero.
  - `cantidad_unidades`: unidades sueltas adicionales, entero mayor o igual a cero.
  - Al menos uno de los dos valores debe ser mayor que cero.
- Los items de respuesta agregan `cantidad_unidades` y `total_unidades`.
- Los pedidos agregan `total_unidades`, calculado como la suma de
  `cantidad_bultos * unidades_por_bulto + cantidad_unidades` de todos sus items.
- Cambio retrocompatible: omitir `cantidad_unidades` equivale a enviar `0`.

### 1.22.0 (2026-06-08)
- Nuevo modulo mobile complementario **Feedback de calle** bajo `/api/v1/feedback`:
  - Motivos, clientes importados por CSV, carga de feedback, historial, bandeja del jefe directo, toma/resolucion y dashboard.
  - La resolucion guarda fecha, descripcion gestionada y `resuelto_en_sla`.
  - El dashboard incluye totales, motivos principales, ranking de carga y posicion personal contra el resto del personal.
- Nuevo modulo mobile complementario **SKAP - Mi Desarrollo** bajo `/api/skap`:
  - Preguntas por sector, evaluacion anual, detalle de evaluacion, mi desarrollo, ranking personal y planes PDP.
  - Usa el mismo Bearer JWT mobile que `/api/v1/mobile`, pero mantiene envelope `{"success":true,"data":...}` propio.

### 1.21.5 (2026-05-28)
- Flutter â€” nueva solapa **"Mes en curso"** en `KpisSectorPage`:
  - Se agrega una segunda pestaÃ±a ("Mes en curso") junto a la existente ("Resumen"). El contenido de "Resumen" queda intacto.
  - Muestra un **calendario mensual del mes en curso** (semana lunesâ€“domingo). Los dÃ­as pasados y hoy son tapeables; los dÃ­as futuros estÃ¡n deshabilitados.
  - **Dots de datos sin llamada extra**: los dÃ­as que ya tienen al menos un resultado cargado muestran un punto debajo del nÃºmero. Se derivan de `series_diaria[].puntos[].resultado_dia` ya cargados en la llamada a endpoint 37A (`GET /me/kpis-sector/resumen?include_series=true`), sin llamadas adicionales.
  - **Tap en un dÃ­a**: llama al endpoint 37B (`GET /me/kpis-sector/dia?fecha=YYYY-MM-DD`) y muestra las tarjetas de KPI para esa fecha. Las respuestas se cachean en memoria durante la sesiÃ³n â€” tocar un dÃ­a ya consultado no genera nueva llamada a la red.
  - Cada tarjeta de KPI muestra: nombre, cÃ³digo, semaforo, `resultado_dia`, `objetivo_dia` y `resultado_acumulado_a_fecha`.
  - Si el dÃ­a no tiene ningÃºn registro (`tiene_resultado = false` para todos los KPIs), se muestra un estado vacÃ­o "Sin registros para este dÃ­a."
  - Sin cambios de payload ni status codes en el backend.

### 1.21.4 (2026-05-28)
- Documentacion explicita de `tipo_acumulacion = "ultimo"` en endpoints 37, 37A y 37B:
  - `resultado_acumulado` / `resultado_mes` para `ultimo` es el **valor mas reciente por fecha**, no un promedio ni una suma.
  - Ideal para indicadores tipo snapshot que se reemplazan al cambiar (NPS, stock, tasas).
  - `objetivo_dia` para `ultimo` es `objetivo_anual` (fijo, igual que `promedio`); no se proratea.
  - Sin cambio de payload ni status codes â€” solo aclaracion semantica y de negocio.
- Panel web: formulario de KPI actualizado con descripciones claras por tipo de acumulacion e indicaciones de uso (NPS â†’ Ultimo, satisfaccion â†’ Promedio, bultos â†’ Suma).
- Panel web: listado de KPIs ahora muestra el tipo de acumulacion con badge de color (azul=suma, naranja=promedio, verde=ultimo) para facilitar la revision de configuracion.

### 1.21.3 (2026-05-28)
- Nuevo endpoint `GET /me/kpis-sector/dia?fecha=YYYY-MM-DD` (endpoint 37B):
  - Snapshot de todos los KPIs activos del sector para una fecha concreta.
  - Siempre devuelve una fila por KPI aunque no haya resultado ese dÃ­a exacto.
  - Cada fila incluye: `tiene_resultado`, `resultado_dia`, `objetivo_dia`, `resultado_acumulado_a_fecha`, `objetivo_acumulado_a_fecha`, `progreso_dia_pct`, `progreso_acumulado_pct`, `semaforo_dia`, `semaforo_acumulado`.
  - Acumulado calculado desde el 1 de enero del aÃ±o de la fecha consultada.
  - `fecha` requerida, no puede ser futura. 400 si falta, es invÃ¡lida o es futura.

### 1.21.2 (2026-05-28)
- `GET /me/kpis-sector/resumen` â€” nueva serie diaria opcional:
  - Params opcionales: `include_series=true` y `series_dias=N` (1â€“365, default 60).
  - Si `include_series=true`, el payload incluye `series_diaria`: lista de KPIs del sector con campo `puntos` (una entrada por dia con resultado real).
  - Cada punto expone: `resultado_dia`, `objetivo_dia`, `resultado_acumulado_a_fecha`, `objetivo_acumulado_a_fecha`, `progreso_dia_pct`, `progreso_acumulado_pct`, `semaforo_dia`, `semaforo_acumulado`.
  - Los acumulados se computan desde el inicio del anio aunque la ventana de display sea menor.
  - Para KPIs `between`, `objetivo_dia` y `objetivo_acumulado_a_fecha` son `null`; se usa `valor_min`/`valor_max`.
  - `meta` ahora incluye siempre `include_series` (bool) y `series_dias` (int o null).
  - Sin `include_series`, el payload es identico al de 1.21.1 (compatible).
  - Nuevo 400: `{"error":"series_dias invalido. Use un entero entre 1 y 365."}`.

### 1.21.1 (2026-05-28)
- Aclaracion de contrato para KPIs mobile:
  - Los resultados provienen de importaciones CSV del panel web.
  - `codigo_kpi` se resuelve por el sector del empleado.
  - Al importar datos del mes actual, backend reemplaza ese mes para los empleados incluidos en el CSV antes de insertar los nuevos datos.
  - Los meses historicos no se limpian masivamente; solo se insertan/actualizan registros coincidentes.
- No cambia el payload ni los status codes de `GET /me/kpis-sector` ni `GET /me/kpis-sector/resumen`.

### 1.21.0 (2026-05-28)
- Nuevo endpoint mobile de KPIs sectoriales enriquecidos:
  - `GET /me/kpis-sector/resumen?anio=YYYY&limit_meses=N`
- No modifica el endpoint existente `GET /me/kpis-sector`.
- Agrega vistas para Flutter:
  - `vista_actual.kpis`: misma informacion de la vista anual actual.
  - `ultimo_cargado`: ultimo resultado de KPI cargado, con `fecha_resultado` y `cargado_at`.
  - `meses_cerrados`: resultados por KPI agrupados por meses calendario cerrados.
- `limit_meses` permite pedir de 1 a 12 meses cerrados; default 6.

### 1.20.5 (2026-05-25)
- **CorrecciÃ³n de flujo calificaciÃ³n (endpoint 53):** el flujo recomendado ahora describe la implementaciÃ³n real con `AppRatingService` + `FlutterSecureStorage`. Se documentan las claves de storage, la lÃ³gica de `shouldShowDialog` (`minSessions=3`, `maxDismissals=2`) y el comportamiento ante `409`.
- **Panel web:** secciÃ³n "Pedidos Empleados" separada del grupo "Asistencia" en la navegaciÃ³n lateral. Incluye Adelantos, Pedidos mercaderÃ­a e Importar catÃ¡logo.

### 1.20.4 (2026-05-24)
- **TelemetrÃ­a de sesiones mobile** â€” registro automÃ¡tico de cada login en tabla `mobile_sesiones`.
  - `POST /auth/login` acepta 3 campos opcionales nuevos: `platform`, `device_model`, `app_version`. Totalmente retrocompatible â€” si Flutter no los envÃ­a, funciona igual y se guardan como nulos.
  - `POST /auth/refresh` actualiza `fecha_ultimo_request` de la sesiÃ³n en curso (sin cambios en la respuesta).
  - El JWT ahora incluye `sesion_id` internamente. Flutter no necesita leerlo.
  - Panel admin web en `/mobile-stats/` (solo admin): KPIs de sesiones hoy/7d/30d, distribuciÃ³n Android/iOS, versiones activas y grÃ¡fico de actividad diaria.
  - Requiere `device_info_plus` en Flutter para enviar modelo del dispositivo. Ver flujo recomendado en endpoint 1.

### 1.20.3 (2026-05-24)
- **Nuevo mÃ³dulo: CalificaciÃ³n de la app** â€” endpoint 53.
  - `POST /api/v1/mobile/calificar-app` â€” envÃ­a puntuaciÃ³n 1â€“5, comentario opcional, pantalla y versiÃ³n de la app.
  - Un empleado puede calificar una vez por versiÃ³n de app (`version_app` nullable; la unicidad por NULL se controla a nivel aplicaciÃ³n).
  - Panel admin web en `/admin/calificaciones-app/` con KPIs, barra de distribuciÃ³n de estrellas y tabla filtrable por fecha, versiÃ³n, puntuaciÃ³n y sector.
  - Tabla MySQL: `app_calificaciones` (migraciÃ³n `20260524_03`).

### 1.20.2 (2026-05-24)
- Changelog reorganizado: entrada 1.20.2 ya documentada â€” ver abajo.

### 1.20.0 (2026-05-24)
- **Nuevo mÃ³dulo: Trivia Operativa** â€” prefijo `/api/v1/trivia/`
- Nuevos endpoints (40â€“52):
  - `GET /trivia/estado` â€” estado general para el empleado (hay trivia, ya participÃ³, resultado propio).
  - `GET /trivia/activa` â€” datos de la trivia activa disponible.
  - `POST /trivia/iniciar` â€” registra inicio de participaciÃ³n; devuelve preguntas sin respuesta correcta.
  - `POST /trivia/finalizar` â€” recibe todas las respuestas, calcula puntaje, correctas, tiempo.
  - `GET /trivia/ranking/<trivia_id>` â€” ranking en tiempo real de una trivia.
  - `GET /trivia/historial` â€” trivias finalizadas con ganador (paginado).
  - `GET /trivia/mi-historial` â€” historial de participaciones del empleado autenticado.
  - `GET /trivia/ganador/<trivia_id>` â€” ganador oficial de una trivia.
  - `GET /trivia/ranking-anual/<anio>` â€” ranking anual acumulado.
  - `GET /trivia/ganador-anual/<anio>` â€” ganador anual definitivo.
  - `GET /trivia/notificaciones` â€” notificaciones no leÃ­das (polling Flutter).
  - `POST /trivia/notificaciones/<id>/leer` â€” marca una notificaciÃ³n como leÃ­da.
  - `POST /trivia/notificaciones/leer-todas` â€” marca todas como leÃ­das.
- Reglas de negocio:
  - Un empleado solo puede participar una vez por trivia (validaciÃ³n backend con UNIQUE constraint).
  - La respuesta correcta nunca se expone en la API.
  - Solo se puede jugar dentro del horario `fecha_inicio`â€“`fecha_fin` con estado `activa`.
  - Preguntas omitidas en `/finalizar` se cuentan como incorrectas.
  - Ranking definitivo: mayor puntaje â†’ menor tiempo â†’ inicio mÃ¡s temprano â†’ fin mÃ¡s temprano.
  - Ranking anual: mayor puntaje acumulado â†’ mÃ¡s trivias ganadas â†’ mÃ¡s correctas â†’ menor tiempo â†’ mÃ¡s participaciones.
- Scheduler automÃ¡tico (APScheduler):
  - Activa trivias cuya `fecha_inicio` llegÃ³ (cada 2 minutos).
  - Finaliza trivias vencidas y calcula ranking definitivo (cada 2 minutos).
  - Genera notificaciones a empleados sin participar: recordatorio 24h y 2h antes del fin (cada 1 hora).
- Panel admin web: `/admin/trivias/` con CRUD de trivias, preguntas, visualizaciÃ³n de ranking y finalizaciÃ³n manual.

### 1.19.0 (2026-05-18)
- **Legajo â€” documentacion bloqueada para empleados:**
  - `GET /me/legajo/adjuntos/<id>` siempre devuelve `403 No autorizado`. Los empleados no pueden descargar documentacion.
  - `GET /me/legajo/eventos` y `GET /me/legajo/eventos/<id>`: se mantiene `adjuntos_count` para mostrar trazabilidad, pero `adjuntos` sigue bloqueado para empleados.
  - `legajo.recientes` dentro de `GET /me/dashboard` actualizado con el mismo esquema reducido.
- **Nuevo endpoint `GET /me/legajo/historial-por-tipo`:**
  - Devuelve todos los tipos de evento activos con `total`, `vigentes` y `ultima_fecha` para el empleado autenticado.
  - Incluye tipos con `total: 0`.
  - Ordenado por total descendente, luego nombre.

### 1.18.0 (2026-05-16)
- Se completa el contrato mobile de legajo:
  - `GET /me/legajo/resumen`
  - `GET /me/legajo/tipos-evento`
  - `GET /me/legajo/eventos` con filtros `desde`, `hasta`, `severidad`, `q`, `tipo_id`, `estado`
  - `GET /me/legajo/eventos/<id>` con adjuntos
  - `GET /me/legajo/adjuntos/<id>` para descarga con Bearer JWT
- Las respuestas nuevas de legajo usan `ok` y errores JSON con `ok=false`.
- Los adjuntos mobile quedan scoped al empleado autenticado.

### 1.20.2 (2026-05-24)
- `GET /vacaciones/resumen` â€” campos nuevos:
  - `desglose_corresponde`: array `[{concepto, dias}]` listo para renderizar cada componente de `dias_corresponden`. Solo incluye conceptos con valor > 0. Soluciona el problema de mostrar "48 dÃ­as" sin contexto; el app puede armar "35 Base LCT + 13 Compensatorios = 48 dÃ­as".
  - `dias_trabajados_porcentaje`: porcentaje de dias trabajados sobre el total habil del periodo. Para mostrar "66 de 102 dÃ­as hÃ¡biles (64.7%)" en lugar de la fraccion cruda.
  - `umbral_proporcional_pct`: siempre `50.0`. Indica el minimo % para no sufrir reduccion proporcional. Util para mostrar un indicador de progreso en la pantalla de saldo.
- `GET /vacaciones/movimientos` â€” campos nuevos por movimiento:
  - `es_reversion`: `true` si el movimiento revierte otro (no afecta saldo, mostrar atenuado).
  - `afecta_saldo`: `false` para rechazados y reversiones. Cuando es `false`, el item debe mostrarse como historial, sin impactar el saldo visible. Incluye aviso UX recomendado.
- Documentacion UX recomendada: padding inferior minimo de 80px en la lista de movimientos para evitar que el FAB flotante tape el ultimo item.
- Tabla completa de referencia de todos los campos de `vacaciones` en el resumen.

### 1.20.1 (2026-05-24)
- `GET /vacaciones/resumen`: respuesta completa documentada con todos los campos devueltos (`dias_habiles_anio_total`, `dias_habiles_evaluados`, `fecha_evaluacion_trabajo`, `aplica_control_proporcional`).
- Se documenta la logica de `dias_compensatorios`: dias extra acreditados por RRHH por sector o empleado, independientes de las vacaciones base. Se suman a `dias_corresponden`.
- Formula explicita: `dias_corresponden = dias_base + dias_compensatorios + dias_ajustes`. Tomar vacaciones descuenta de este total indiferentemente de su origen.
- Flujo Flutter recomendado para pantalla de saldo de vacaciones incluido.
- Correccion del calculo proporcional para nuevos ingresos: el denominador ahora usa los dias habiles desde la fecha de ingreso (no desde el 1 de enero), evitando penalizar incorrectamente a empleados con ingreso posterior a enero.

### 1.17.0 (2026-05-15)
- Nuevos endpoints mobile para vacaciones con saldo LCT:
  - `GET /vacaciones/resumen?anio=YYYY`
  - `GET /vacaciones/movimientos?anio=YYYY`
  - `POST /vacaciones/solicitar`
- `POST /vacaciones/solicitar` valida saldo disponible contra `dias_disponibles_con_pendientes` y crea un movimiento `tomado` en estado `pendiente`.
- Se documenta que `/me/vacaciones*` queda como compatibilidad sobre movimientos, mientras el flujo mobile recomendado usa los endpoints de saldo/movimientos.

### 1.16.1 (2026-05-13)
- `POST /me/fichadas/scan`: `qr_token` acepta JWT directo, `Bearer`, URL con query o JSON con `qr_token`.
- `POST /me/fichadas/scan`: errores QR devuelven `code` especifico (`qr_token_invalid_signature`, `qr_token_expired`, `qr_inactive`, etc.).
- `POST /me/qr`: default real de `vigencia_segundos` alineado al contrato (`2592000`, 30 dias).
- QR puerta: los QRs generados desde el panel quedan registrados y pueden inactivarse; un QR inactivo se rechaza en mobile.

### 1.15.0 (2026-04-20)
- `GET /me/kpis-sector`: nuevos campos por KPI: `condicion`, `condicion_simbolo`, `valor_min`, `valor_max`.
- Soporte condicion `between`: el semaforo evalua si el resultado cae dentro del rango [valor_min, valor_max].
- Semaforo `between`: verde=dentro del rango, amarillo=dentro del 10% del margen exterior, rojo=fuera.
- Para KPIs `promedio`/`ultimo`, el ritmo esperado ya no aplica fraccion anual (siempre compara contra el objetivo completo).

### 1.14.0 (2026-04-19)
- Nuevo endpoint KPIs sectoriales:
  - `GET /me/kpis-sector?anio=YYYY`
- Devuelve por KPI: objetivo anual del sector, resultado acumulado del empleado, semaforo y recomendacion.
- Semaforo: `verde` / `amarillo` / `rojo` basado en ritmo esperado lineal vs real.
- Los resultados se cargan diariamente via CSV en el panel web.

### 1.13.1 (2026-04-19)
- Se completa el contrato mobile de pedidos de mercaderia con:
  - esquema explicito de `PedidoMercaderiaItem`
  - flujo recomendado para Flutter
  - validaciones de alta
  - respuestas de error para edicion y cancelacion

### 1.13.0 (2026-04-18)
- Nuevos endpoints de pedidos de mercaderia para mobile:
  - `GET /me/pedidos-mercaderia/resumen`
  - `GET /me/pedidos-mercaderia/estado`
  - `GET /me/pedidos-mercaderia/articulos`
  - `GET /me/pedidos-mercaderia`
  - `GET /me/pedidos-mercaderia/<id>`
  - `POST /me/pedidos-mercaderia`
  - `PUT /me/pedidos-mercaderia/<id>`
  - `DELETE /me/pedidos-mercaderia/<id>`
- Reglas nuevas de negocio:
  - solo se permite un pedido de mercaderia por empleado por mes calendario
  - un pedido `pendiente` puede editarse o cancelarse
  - las cantidades se informan solo en `bultos`
- `GET /me/pedidos-mercaderia/articulos` expone solo articulos importados con:
  - `Activo = SI`
  - `Anulado = NO`
  - `Usado en dispositivo movil = SI`
  - `TIPO DE PRODUCTO = MERCADERIA`

### 1.12.3 (2026-04-18)
- Nuevo endpoint mobile de resumen para la pantalla inicial:
  - `GET /me/adelantos/resumen`
- Devuelve:
  - `adelanto_mes_actual`
  - `ultimo_adelanto`
  - `total_historial`
  - `pendientes_total`

### 1.12.2 (2026-04-18)
- Nuevo endpoint mobile de detalle de adelanto:
  - `GET /me/adelantos/<id>`

### 1.12.1 (2026-04-18)
- Nuevo endpoint mobile de historial de adelantos:
  - `GET /me/adelantos` (lista paginada con filtro opcional `estado`)
- `AdelantoItem` ahora puede incluir:
  - `resuelto_at`
  - `resuelto_by_usuario`

### 1.12.0 (2026-04-17)
- Nuevos endpoints de adelantos para mobile:
  - `GET /me/adelantos/estado` (consulta si ya existe solicitud en el mes actual)
  - `POST /me/adelantos` (crea la solicitud del mes actual)
- Regla nueva de negocio:
  - solo se permite un adelanto por empleado por mes calendario

### 1.11.0 (2026-03-26)
- Nuevos endpoints: CRUD completo de justificaciones:
  - `GET /me/justificaciones` (lista paginada con filtros `desde`, `hasta`, `estado`)
  - `GET /me/justificaciones/<id>`
  - `POST /me/justificaciones`
  - `PUT /me/justificaciones/<id>` (solo estado `pendiente`)
  - `DELETE /me/justificaciones/<id>` (solo estado `pendiente`)
- Justificaciones: ahora aceptan una `fecha` operativa propia para poder registrar una justificacion aunque no exista `asistencia_id` para ese dia.
- Nuevos endpoints: CRUD completo de vacaciones:
  - `GET /me/vacaciones`, `GET /me/vacaciones/<id>`
  - `POST /me/vacaciones`, `PUT /me/vacaciones/<id>`, `DELETE /me/vacaciones/<id>`
- Nuevos endpoints: horarios asignaciones:
  - `GET /me/horarios-asignaciones` (historial)
  - `GET /me/horarios-asignaciones/actual` (con dias de la semana)
- Nuevos endpoints: francos:
  - `GET /me/francos`, `GET /me/francos/<id>`
- Nuevos endpoints: legajo:
  - `GET /me/legajo/eventos` (con filtros `tipo_id`, `estado`)
  - `GET /me/legajo/eventos/<id>`
- Nuevo endpoint dashboard consolidado: `GET /me/dashboard`
  - Combina estadisticas de asistencia + eventos de legajo + vacaciones activas + francos proximos + horario actual
  - Params: `periodo` (`7d`|`30d`|`mes_actual`|`90d`) + override `desde`/`hasta`
- `GET /me/estadisticas` ampliado:
  - 7 nuevos campos en `kpis`: `adherencia_pct`, `horas_promedio`, `horas_totales`, `gps_incidencias`, `dias_laborables`, `dias_con_registro`, `racha_ok`
  - Nuevo campo en `justificaciones`: `tasa_justificacion_pct`
  - Nueva serie en `series`: `semanal` (resumen por semana ISO)

### 1.10.0 (2026-03-09)
- `POST /api/v1/mobile/auth/login` agrega `empleado.imagen_version`.
- `GET /api/v1/mobile/me` agrega `imagen_version`.
- `PUT /api/v1/mobile/me/perfil` agrega `imagen_version` en response.
- `DELETE /api/v1/mobile/me/perfil/foto` agrega `imagen_version` en response (`null`).
- Nuevo endpoint de imagen para cliente mobile: `GET /empleados/imagen/<dni>?v=<imagen_version>` con soporte `ETag/304`.

### 1.9.0 (2026-02-28)
- `PUT /api/v1/mobile/me/perfil` agrega `eliminar_foto=true` para baja de foto.
- Nuevo endpoint `DELETE /api/v1/mobile/me/perfil/foto`.

### 1.8.0 (2026-02-28)
- `PUT /api/v1/mobile/me/perfil` soporta `multipart/form-data` con `foto_file`.

### 1.7.0 (2026-02-27)
- Nuevo endpoint: `GET /api/v1/mobile/me/estadisticas`.

### 1.6.0 (2026-02-25)
- `GET /api/v1/mobile/me/config-asistencia` agrega `cooldown_scan_segundos` e `intervalo_minimo_fichadas_minutos`.
- `POST /api/v1/mobile/me/fichadas/scan` agrega `code` y `cooldown_segundos_restantes` en 409 por doble scan.

### 1.5.0 (2026-02-24)
- Se mantiene `POST /api/v1/mobile/me/fichadas/scan` como endpoint recomendado.
- Se marcan `deprecated`: `/fichadas/entrada` y `/fichadas/salida`.
- Se agrega base URL de produccion.

