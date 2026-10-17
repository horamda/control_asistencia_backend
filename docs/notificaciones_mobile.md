# Bandeja de notificaciones (campana) — contrato para Flutter y la app web (1.51.0)

La campana muestra una **bandeja persistente**: cada novedad queda guardada en el servidor y el push solo avisa.

- **Siempre queda en la bandeja.** Aunque el push falle, el celular no tenga permiso de notificaciones o el
  empleado descarte el aviso, la novedad sigue ahí.
- **Contador.** `no_leidas` es el número de la campana y vale para todos los dispositivos y la web.
- **Lectura.** Solo marca como leída tocar la notificación o abrir su pantalla. Recibir el push no la marca, ni
  consultar el listado tampoco.
- **Solicitudes pendientes.** Una solicitud que sigue pendiente no genera avisos nuevos ni vuelve a quedar sin leer:
  las notificaciones nacen de un evento, no de una consulta.

Reemplaza a las alertas que la app calculaba con los resúmenes de cada módulo (ver [Retiro de las alertas viejas](#retiro-de-las-alertas-calculadas-en-flutter)).

Base: `/api/v1/mobile` · JWT mobile en `Authorization: Bearer <token>` · empresa y empleado salen del token.
OpenAPI: `mobile_v1_openapi.yaml`, tag **Notificaciones**.

## Endpoints

| Método y ruta | Para qué |
|---|---|
| `GET /me/notificaciones` | Listado paginado, de la más nueva a la más vieja. No marca nada. |
| `GET /me/notificaciones/resumen` | Contador de la campana (liviano). |
| `GET /me/notificaciones/{id}` | Detalle, con la disponibilidad del trámite relacionado. No la marca. |
| `POST /me/notificaciones/{id}/leer` | Marcar como leída. Idempotente. Devuelve el contador. |
| `POST /me/notificaciones/leer-todas` | Marcar como leídas hasta el corte. Devuelve el contador. |

### `GET /me/notificaciones`

| Parámetro | Valores | Por defecto |
|---|---|---|
| `estado` | `todas`, `no_leidas`, `leidas` | `todas` |
| `modulo` | ver [módulos](#qué-eventos-generan-notificaciones) | todos |
| `antes_de` | cursor: el `siguiente` de la página anterior | — (primera página) |
| `limite` | 1 a 50 | 20 |

Respuesta:

```json
{
  "items": [
    {
      "id": 812,
      "tipo": "adelanto",
      "modulo": "adelantos",
      "titulo": "Adelanto aprobado",
      "mensaje": "Tu pedido de adelanto de octubre fue aprobado.",
      "creado_at": "2026-10-17T10:42:05",
      "leida": false,
      "leido_at": null,
      "referencia": {"tipo": "adelanto", "id": 57},
      "destino": {"ruta": "/adelantos", "parametros": {"adelanto_id": "57", "estado": "aprobado"}}
    },
    {
      "id": 790,
      "tipo": "comunicado",
      "modulo": "comunicados",
      "titulo": "Corte de luz",
      "mensaje": "El jueves no hay luz de 8 a 12. Traigan linterna.",
      "creado_at": "2026-10-16T09:00:00",
      "leida": true,
      "leido_at": "2026-10-16T09:14:31",
      "referencia": {"tipo": "comunicado", "id": 31},
      "destino": {"ruta": "/comunicados/31", "parametros": {"comunicado_id": "31"}}
    }
  ],
  "no_leidas": 3,
  "corte": 812,
  "siguiente": 790,
  "limite": 2
}
```

- `no_leidas`: total del empleado, no depende de filtros ni de la página.
- `corte`: id de la notificación más nueva al momento de consultar. Guardarlo para "leer todas".
- `siguiente`: pasarlo como `antes_de` para la página siguiente; `null` si no hay más. El orden es estable
  (por `id`), así que paginar mientras llegan notificaciones nuevas no repite ni saltea.
- `creado_at` / `leido_at`: hora Argentina, sin zona (igual que el resto de la API).

### `GET /me/notificaciones/resumen`

```json
{"no_leidas": 3, "por_modulo": {"adelantos": 1, "comunicados": 2}, "ultima_id": 812}
```

Para el número de la campana y para saber si hay algo nuevo sin bajar el listado (`ultima_id` cambió).

### `GET /me/notificaciones/{id}`

La misma notificación más `no_leidas` y `referencia.disponible`:

```json
{
  "id": 812, "tipo": "adelanto", "modulo": "adelantos", "titulo": "Adelanto aprobado",
  "mensaje": "Tu pedido de adelanto de octubre fue aprobado.", "creado_at": "2026-10-17T10:42:05",
  "leida": false, "leido_at": null,
  "referencia": {"tipo": "adelanto", "id": 57, "disponible": true},
  "destino": {"ruta": "/adelantos", "parametros": {"adelanto_id": "57", "estado": "aprobado"}},
  "no_leidas": 3
}
```

`disponible`:

| Valor | Qué significa | Qué hacer |
|---|---|---|
| `true` | El trámite existe y el empleado puede verlo. | Navegar a `destino.ruta`. |
| `false` | El trámite ya no existe o dejó de ser accesible. | Mostrar el mensaje igual y no navegar (o mostrar "Este trámite ya no está disponible"). |
| `null` | No se pudo verificar. | Navegar: la pantalla de destino valida el acceso. |

En las solicitudes para revisar (`revision_pendiente`), `disponible` solo dice si la solicitud existe. El permiso
de quien aprueba lo valida la pantalla de revisión.

404 si la notificación no existe o es de otro empleado o empresa.

### `POST /me/notificaciones/{id}/leer`

Sin cuerpo. Devuelve la notificación con `leida: true`, su `leido_at` y `no_leidas` actualizado:

```json
{"id": 812, "leida": true, "leido_at": "2026-10-17T10:45:12", "no_leidas": 2, "...": "resto de los campos"}
```

- **Idempotente:** la primera lectura guarda la fecha; repetirla, desde este u otro dispositivo, devuelve la
  misma fecha.
- **No toca el trámite:** leer un "Adelanto aprobado" no cambia el adelanto.
- **Comunicados:** también queda leído en `/comunicados`, y al revés.

### `POST /me/notificaciones/leer-todas`

```json
{"hasta_id": 812}
```

(opcional `"modulo": "adelantos"` para marcar solo ese módulo)

```json
{"marcadas": 3, "no_leidas": 1, "hasta_id": 812}
```

Marca **solo** las notificaciones con `id <= hasta_id`. Lo que llegó después de que la app bajó el listado
sigue sin leer: en el ejemplo, `no_leidas: 1` es la que llegó en el medio. Es idempotente. Sin `hasta_id`
responde 400.

## Push

Cada push que tiene notificación en la bandeja trae `data.notificacion_id`, además de lo de siempre (`tipo`,
`ruta`, ids, `envio_id`, `acuse`):

```json
{
  "message": {
    "notification": {"title": "Adelanto aprobado", "body": "Tu pedido de adelanto de octubre fue aprobado."},
    "data": {
      "tipo": "adelanto",
      "adelanto_id": "57",
      "estado": "aprobado",
      "ruta": "/adelantos",
      "notificacion_id": "812",
      "envio_id": "4410",
      "acuse": "9f2c…"
    }
  }
}
```

- **Llegada:** recibir el push no es leer. Seguir mandando el acuse `recibido` como hasta ahora (`POST /push/acuse`).
- **Al tocarlo:** acuse `abierto` y, después, `POST /me/notificaciones/{notificacion_id}/leer`. Si se quiere
  validar el destino, antes `GET /me/notificaciones/{notificacion_id}` (`referencia.disponible`).
- **Sin `notificacion_id`:** pasa en un resumen de varios avisos (`data.cantidad`), en los recordatorios y en
  la prueba. Abrir la bandeja (o `data.ruta`).
- **Contenido:** el push no lleva datos sensibles. Solo el título, un texto corto y los ids para navegar.

## Qué eventos generan notificaciones

Una notificación se crea **una vez por evento y por destinatario** (clave única), en la misma transacción que el
push. Los reintentos del push y un mismo evento avisado dos veces no la duplican. Consultar endpoints no crea
nada.

| `tipo` | `modulo` | Cuándo | `referencia.tipo` |
|---|---|---|---|
| `comunicado` | `comunicados` | RR. HH. envía un comunicado (al momento o programado) | `comunicado` |
| `adelanto` | `adelantos` | Adelanto aprobado o rechazado | `adelanto` |
| `pedido_mercaderia` | `pedidos_mercaderia` | Pedido de mercadería aprobado o rechazado | `pedido_mercaderia` |
| `feedback_asignado` | `feedback` | Al responsable: feedback nuevo para resolver | `feedback` |
| `feedback_resuelto` | `feedback` | Al que lo cargó: su feedback se resolvió | `feedback` |
| `reintegro` | `reintegros` | Viáticos aprobados, rechazados, devueltos para corregir o pagados | `reintegro` |
| `reunion_nueva`, `reunion_cambio` | `reuniones` | Reunión nueva, o cambio de días, horario o lugar | `reunion` |
| `reunion_cancelada`, `reunion_reactivada`, `reunion_horario` | `reuniones` | Fecha cancelada, reactivada o con otro horario | `reunion` |
| `justificacion` | `justificaciones` | Justificación aprobada o rechazada | `justificacion` |
| `vacaciones` | `vacaciones` | Vacaciones, compensatorio o ajuste resuelto | `vacaciones` |
| `epp_resuelto`, `epp_entregado` | `epp` | Pedido de EPP resuelto o entregado | `epp` |
| `seguridad_resultado` | `seguridad` | A quien reportó: reporte aprobado o rechazado | `seguridad_evento` |
| `seguridad_accion` (asignada) | `seguridad` | Al responsable: acción correctiva asignada | `seguridad_accion` |
| `trivia_nueva` | `trivias` | Se abrió una trivia | `trivia` |
| `revision_pendiente` | `revisiones` | A jefe / RR. HH. / Seguridad: una solicitud nueva o reenviada para revisar | según `parametros.modulo` |

**No generan notificación** (siguen solo por push, porque pasado el momento no sirven):

- `recordatorio`: la reunión está por empezar.
- `salida_pendiente`: la salida sigue sin fichar.
- `trivia_recordatorio`: quedan 24 h o 2 h.
- `reintegro_recordatorio`: los viáticos del día 5.
- `seguridad_accion` por vencer o vencida.
- `prueba`.

Tampoco se crean notificaciones por el solo hecho de que una solicitud siga pendiente, ni al consultar un
módulo.

**Reglas de la empresa** (Comunicados → Configuración de avisos):

- **Aviso desactivado:** no hay push ni notificación.
- **Horario de silencio o resumen:** la notificación aparece en la bandeja al momento y el push sale después.

## Migración y compatibilidad

- **Tabla nueva:** `empleado_notificaciones`, versión `20261017_notificaciones` de `scripts/bootstrap_schema.py`.
- **Comunicados:** la migración copia los comunicados ya enviados **con su lectura**, así la campana arranca con
  lo que el empleado tenía en Comunicados.
- **Sin históricos ni push:** no importa trámites viejos (adelantos, viáticos, feedback…) ni envía push. Es
  idempotente.
- **Endpoints viejos:** `/comunicados` (bandeja, detalle, `leido`, `leer-todos`) siguen iguales y sincronizan la
  lectura con la bandeja. Las apps instaladas no cambian.
- **Trivias:** `/api/v1/trivia/notificaciones` (el aviso propio de la pantalla de trivias) sigue igual. Para la
  campana usar `/me/notificaciones`.
- **Sin push:** sin Firebase configurado la bandeja funciona igual; solo no salen los push.
- **Fichado:** no cambia la lógica ni los endpoints de fichado de asistencia.

## Despliegue y reversión

1. **Desplegar el backend** (Railway, desde `main`). Al arrancar, `bootstrap_schema` crea la tabla y copia los
   comunicados. Es una sola consulta, sin bloqueos largos, y se puede repetir.
2. **Verificar:**
   - `GET /api/v1/mobile/me/notificaciones/resumen` con un token de prueba devuelve `no_leidas`.
   - Un comunicado nuevo aparece en la bandeja.
3. **Publicar la app** con la campana nueva. Hasta entonces la app vieja sigue usando `/comunicados` y sus
   alertas calculadas, sin cambios.

Si `/me/notificaciones` responde 503, la migración no corrió todavía. Se puede correr a mano con
`python -m scripts.migrate_20261017_02_notificaciones`.

**Reversión:**

- **Volver al commit anterior:** los módulos vuelven a encolar solo push, `/comunicados` sigue funcionando y la
  app vieja no usa la bandeja.
- **Borrar la tabla (opcional):**
  `DROP TABLE empleado_notificaciones; DELETE FROM app_schema_versions WHERE version='20261017_notificaciones';`.
  Los comunicados y sus lecturas no se tocan.

## Guía para integrar en Flutter

1. **Campana**
   - Al abrir la app, al volver a primer plano y al recibir un push en primer plano:
     `GET /me/notificaciones/resumen` y mostrar `no_leidas`.
   - No hace falta un intervalo de consulta corto: el push avisa.
2. **Pantalla Notificaciones**
   - `GET /me/notificaciones?limite=20` y guardar `corte`.
   - Scroll infinito con `antes_de = siguiente`, hasta `siguiente == null`.
   - Pestañas con `estado=no_leidas` o un filtro por `modulo` si se quiere.
3. **Tocar una notificación**
   1. `POST /me/notificaciones/{id}/leer`, actualizar el ítem y la campana con `no_leidas`.
   2. Navegar a `destino.ruta`, con `destino.parametros` para los ids.
   3. Si se quiere evitar pantallas vacías, antes `GET /me/notificaciones/{id}`. Con
      `referencia.disponible == false`, mostrar el mensaje y "Ya no está disponible".
4. **"Marcar todas como leídas"**
   - `POST /me/notificaciones/leer-todas` con `{"hasta_id": corte}` del último listado.
   - Después refrescar: lo que llegó en el medio queda sin leer.
5. **Push**
   - **En primer plano:** refrescar el resumen y, si la pantalla está abierta, el listado.
   - **Al tocarlo:** acuse `abierto` y, con `data.notificacion_id`, leerla y navegar como en el paso 3. Sin ese
     dato, abrir la bandeja o `data.ruta`.
6. **Comunicados**
   - La pantalla de comunicados puede seguir igual: `GET /comunicados/{id}` marca leído y la bandeja se entera.
   - Desde la bandeja, un comunicado navega a `/comunicados/{id}`.
7. **Varias sesiones**
   - Sin caché propia del estado leído: el servidor es la fuente de verdad.
   - Si otro dispositivo la leyó, el próximo listado ya la muestra leída.

### Retiro de las alertas calculadas en Flutter

Cuando la versión con la campana nueva esté publicada:

- **Quitar el cálculo viejo:** las alertas armadas a partir de los resúmenes de adelantos, pedidos de mercadería y
  feedback (la vieja "campana de Alertas" del home), y cualquier contador local de no leídos.
- **Una sola fuente:** la campana usa únicamente `no_leidas` de `/me/notificaciones/resumen`.
- **Lo pendiente de revisar:** las solicitudes que esperan aprobación ya llegan como `revision_pendiente`, una vez
  por solicitud. Si se quiere mostrar cuántas hay pendientes, eso es un dato del módulo (su listado), no de la
  campana.
