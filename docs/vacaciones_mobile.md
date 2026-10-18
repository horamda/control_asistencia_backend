# Vacaciones por semanas y "Mi equipo" — contrato para Flutter y la web de empleados (1.53.0)

Base: `/api/v1/mobile` · JWT mobile en `Authorization: Bearer <token>` · empleado y empresa salen del token.
OpenAPI: `mobile_v1_openapi.yaml`, tag **Vacaciones**.

## Reglas

- **Semanas completas.** Se piden semanas del calendario, de lunes a domingo, corridas o no. Las semanas seguidas
  forman una **tanda**; las sueltas, tandas aparte. Todo va en una sola **solicitud**.
- **Lunes feriado** (Ley de Contrato de Trabajo, art. 151): si el lunes es día no laborable, la tanda empieza el
  primer día hábil siguiente y dura los mismos 7 días corridos por semana. Por ejemplo, 2 semanas con el lunes
  23/11 feriado van del martes 24/11 al lunes 07/12. Si el lunes y el martes son feriados, va de miércoles a martes.
  Los feriados salen del calendario de días no laborables del panel (general, de la empresa o de la sucursal del
  empleado). Un feriado en medio de las vacaciones no cambia nada.
- **Saldo.** Lo que corresponde por antigüedad (14, 21, 28 o 35 días), más compensatorios y ajustes, menos lo
  tomado y lo pendiente. El total pedido no puede superarlo. **Solo semanas completas:** si sobran días que no
  llegan a una semana (proporcional, compensatorios), no se piden desde la app; los carga RR. HH. en el panel.
- **Año.** Una tanda descuenta del año en que empieza, aunque termine en enero.
- **Fechas.** Solo semanas futuras. Una tanda no puede pisarse con otras vacaciones pedidas o aprobadas.
- **Cancelar.** El empleado cancela lo pendiente al momento. Para dar de baja unas vacaciones aprobadas que todavía
  no empezaron, se pide la cancelación y la resuelve su jefe directo o RR. HH. Lo que ya empezó no se cancela
  desde la app.
- **Jefes.** El jefe ve las vacaciones de **toda su cadena** (sus reportes, los reportes de ellos, etc.) y
  **aprueba solo a sus reportes directos**. Un empleado sin jefe y con reportes a cargo (los dueños) ve toda la
  empresa y aprueba a sus directos. Quien no tiene jefe ni reportes no ve a nadie. RR. HH. sigue aprobando
  cualquiera desde el panel. Usa el "Jefe directo" de la ficha del empleado.

## Endpoints

### Empleado

| Método y ruta | Para qué |
|---|---|
| `GET /me/vacaciones/semanas?anio=` | Calendario de semanas del año, con su estado y el saldo en semanas. |
| `POST /me/vacaciones/semanas` | Pedir semanas. |
| `GET /me/vacaciones/solicitudes?anio=` | Mis solicitudes. |
| `GET /me/vacaciones/solicitudes/{id}` | Una solicitud. |
| `POST /me/vacaciones/solicitudes/{id}/cancelar` | Cancelar lo pendiente o pedir la cancelación de lo aprobado. |

### Mi equipo (jefes y dueños)

| Método y ruta | Para qué |
|---|---|
| `GET /me/equipo/vacaciones?estado=&anio=` | Solicitudes de la cadena. `estado=pendiente` trae lo que espera respuesta (incluidas las cancelaciones pedidas). |
| `GET /me/equipo/vacaciones/calendario?mes=AAAA-MM` | Tandas pendientes y aprobadas que tocan el mes (para un Gantt). |
| `GET /me/equipo/vacaciones/saldos?anio=` | Saldo de cada uno. |
| `GET /me/equipo/vacaciones/solicitudes/{id}` | Detalle. |
| `POST /me/equipo/vacaciones/solicitudes/{id}/aprobar` | Aprobar (solo el jefe directo). |
| `POST /me/equipo/vacaciones/solicitudes/{id}/rechazar` | Rechazar con `{"motivo": "..."}` (obligatorio). |
| `POST /me/equipo/vacaciones/solicitudes/{id}/cancelacion/aprobar` | Aceptar el pedido de cancelación. |
| `POST /me/equipo/vacaciones/solicitudes/{id}/cancelacion/rechazar` | Mantener las vacaciones, con `{"motivo": "..."}`. |

**Errores:** `{"error": "mensaje listo para mostrar"}`.

| Código | Cuándo |
|---|---|
| 400 | Regla incumplida (no es lunes, semana pasada, se superpone, falta el motivo). |
| 401 | Sesión inválida. |
| 403 | No es su jefe directo. |
| 404 | No existe o no está en su cadena. |
| 409 | Saldo insuficiente. |

### Endpoints anteriores (compatibles)

`POST /me/vacaciones`, `POST /vacaciones/solicitar` y `PUT /me/vacaciones/{id}` siguen recibiendo
`fecha_desde`/`fecha_hasta`, pero el rango tiene que ser de semanas completas (con el inicio corrido si el lunes es
feriado). Si no, responden 400 con `"Las vacaciones se piden por semanas completas…"`.

`DELETE /me/vacaciones/{id}` tiene dos comportamientos:

- **Pendiente:** la cancela. Responde `{"ok": true, "cancelacion_pedida": false, "mensaje": "Solicitud cancelada."}`.
- **Aprobada:** pide la cancelación. Responde `{"ok": true, "cancelacion_pedida": true, "mensaje": "Pedido de
  cancelación enviado a tu jefe."}`. Antes la cancelaba directamente.

`GET /me/vacaciones` suma `solicitud_id`, `estado` y `cancelacion_pedida` (aditivos).

## Ejemplos

### `GET /me/vacaciones/semanas?anio=2026`

```json
{
  "anio": 2026,
  "zona_horaria": "America/Argentina/Buenos_Aires",
  "calculado_at": "2026-10-18T10:00:00-03:00",
  "saldo": {"dias_corresponden": 28, "dias_tomados": 0, "dias_pendientes": 14, "dias_disponibles": 14,
            "semanas_disponibles": 2, "dias_fuera_de_semanas": 0},
  "feriados_cargados": true,
  "reglas": "Las vacaciones se piden por semanas completas, de lunes a domingo. Si el lunes es feriado empiezan el primer día hábil siguiente y duran los mismos 7 días.",
  "semanas": [
    {"lunes": "2026-10-12", "domingo": "2026-10-18", "inicio": "2026-10-12", "fin": "2026-10-18", "feriado_lunes": null, "estado": "pasada", "solicitud_id": null},
    {"lunes": "2026-11-23", "domingo": "2026-11-29", "inicio": "2026-11-24", "fin": "2026-11-30", "feriado_lunes": "Soberanía", "estado": "pendiente", "solicitud_id": 1},
    {"lunes": "2026-12-14", "domingo": "2026-12-20", "inicio": "2026-12-14", "fin": "2026-12-20", "feriado_lunes": null, "estado": "disponible", "solicitud_id": null}
  ]
}
```

- **`estado` de cada semana:**

  | Valor | Qué significa |
  |---|---|
  | `disponible` | Se puede elegir. |
  | `pendiente` / `aprobada` | La ocupa una solicitud (ver `solicitud_id`). |
  | `pasada` | Ya empezó. |
  | `sin_dias_habiles` | Toda la semana es no laborable. |

  Una tanda corrida (que termina un lunes) también marca como ocupada la semana siguiente.
- **`inicio` / `fin`:** las fechas reales si esa semana se pide sola. Con `feriado_lunes` la app puede mostrar
  "Empieza el martes 24/11 (lunes feriado: Soberanía)".
- **`feriados_cargados = false`:** el calendario de ese año todavía no tiene días no laborables. Conviene avisar
  "Las fechas pueden ajustarse si hay feriados".
- **Saldo:**
  - Mostrar `semanas_disponibles` ("Te quedan 2 semanas").
  - Si `dias_fuera_de_semanas > 0`, mostrar aparte "N días para coordinar con RR. HH.".
  - Deshabilitar la selección cuando se llega a `semanas_disponibles`.

### `POST /me/vacaciones/semanas`

```json
{"semanas": ["2026-11-23", "2026-11-30", "2027-01-04"], "observaciones": "Viaje"}
```

201:

```json
{
  "id": 1,
  "empleado": {"id": 10, "nombre": "Perez Ana", "legajo": "0010"},
  "estado": "pendiente",
  "dias": 21,
  "creado_at": "2026-10-18T18:26:33",
  "observacion": "Viaje",
  "tandas": [
    {"movimiento_id": 1, "fecha_desde": "2026-11-24", "fecha_hasta": "2026-12-07", "dias": 14, "semanas": 2,
     "anio": 2026, "estado": "pendiente", "inicio_corrido": true, "empezo": false, "motivo_resolucion": null,
     "resuelto_por": null, "resuelto_at": null, "cancelacion_pedida": false, "cancelacion_motivo": null},
    {"movimiento_id": 2, "fecha_desde": "2027-01-04", "fecha_hasta": "2027-01-10", "dias": 7, "semanas": 1,
     "anio": 2027, "estado": "pendiente", "inicio_corrido": false, "empezo": false, "motivo_resolucion": null,
     "resuelto_por": null, "resuelto_at": null, "cancelacion_pedida": false, "cancelacion_motivo": null}
  ],
  "pendiente": true,
  "cancelacion_pedida": false,
  "puede_cancelar": true,
  "puede_resolver": false,
  "puede_resolver_cancelacion": false
}
```

- **Estado de la solicitud:** `pendiente`, `aprobada`, `rechazada`, `cancelada` o `parcial` (tandas en estados
  distintos, por ejemplo una aprobada y otra cancelada).
- **Estado de cada tanda:** `pendiente`, `aprobado`, `rechazado` o `cancelada`.
- **`resuelto_por`:** el nombre del jefe, o "RR. HH." si se resolvió en el panel.
- **`inicio_corrido`:** empieza después del lunes por feriado.

### `GET /me/equipo/vacaciones?estado=pendiente`

```json
{"alcance": "equipo", "es_jefe": true, "por_resolver": 1, "items": [ { "...": "solicitudes con el formato anterior" } ]}
```

- **`alcance`:** `equipo` (su cadena), `empresa` (dueño) o `sin_equipo`.
- **`por_resolver`:** cuántas puede aprobar o rechazar (sus directos), para el número de la pestaña.
- **Botones:** mostrar "Aprobar / Rechazar" solo con `puede_resolver` y "Aceptar / Mantener" solo con
  `puede_resolver_cancelacion`. El resto de la cadena se ve sin botones.

### `GET /me/equipo/vacaciones/saldos?anio=2026`

```json
{"anio": 2026, "alcance": "equipo", "items": [
  {"empleado": {"id": 10, "nombre": "Perez Ana", "legajo": "0010"}, "es_directo": true, "error": null,
   "dias_corresponden": 28, "dias_tomados": 0, "dias_pendientes": 14, "dias_disponibles": 14, "semanas_disponibles": 2},
  {"empleado": {"id": 12, "nombre": "Sucursal Otra", "legajo": "0012"}, "es_directo": false, "error": null,
   "dias_corresponden": 14, "dias_tomados": 0, "dias_pendientes": 0, "dias_disponibles": 14, "semanas_disponibles": 2}]}
```

### `GET /me/equipo/vacaciones/calendario?mes=2026-11`

```json
{"mes": "2026-11", "desde": "2026-11-01", "hasta": "2026-11-30", "alcance": "equipo", "items": [
  {"solicitud_id": 1, "movimiento_id": 1, "empleado": {"id": 10, "nombre": "Perez Ana", "legajo": "0010"},
   "fecha_desde": "2026-11-24", "fecha_hasta": "2026-12-07", "dias": 14, "semanas": 2, "estado": "pendiente",
   "inicio_corrido": true, "...": "resto de los campos de la tanda"}]}
```

## Avisos (push y bandeja)

| Momento | A quién | `tipo` | Bandeja |
|---|---|---|---|
| El empleado pide | Jefe directo (y RR. HH. si la regla lo incluye) | `revision_pendiente` (`modulo: vacaciones`) | Sí |
| El empleado pide cancelar unas aprobadas | Jefe directo (y RR. HH.) | `revision_pendiente`, `data.evento = cancelacion` | Sí |
| Aprobada, rechazada, cancelada, cancelación rechazada, cargada por RR. HH. | El empleado | `vacaciones`, `data.evento` = `aprobada` / `rechazada` / `cancelada` / `cancelacion_rechazada` / `cargada` | Sí |
| Sigue pendiente N días antes de empezar | Jefe del jefe directo y/o RR. HH. (regla "Vacaciones sin resolver") | `revision_pendiente`, `data.evento = escalada` | Sí |
| Día hábil anterior al inicio | El empleado y, si se elige, su jefe | `vacaciones_inicio` / `vacaciones_equipo` | No (solo push) |

- **Uno por solicitud:** "Perez Ana pidió 3 semanas: del 24/11 al 07/12 y del 04/01 al 10/01 (21 días)." y
  "Tus vacaciones del 24/11 al 07/12 y del 04/01 al 10/01 fueron aprobadas (21 días) por Garcia Luis.".
- **Datos del push:**
  - `data.solicitud_id`.
  - `data.ruta`: `/vacaciones/{solicitud_id}` para el empleado, `/equipo/vacaciones/{solicitud_id}` para el jefe.
  - `data.evento`, y `data.notificacion_id` si queda en la bandeja.
- **Al resolverse** (aprobada, rechazada o cancelada por el empleado):
  - Se borran los push "para revisar" que todavía no salieron.
  - La notificación de los revisores queda leída.
  - El empleado no recibe aviso de su propia cancelación.
- **Configuración:** todo se configura en el panel, en **Comunicados → Configuración de avisos** ("Vacaciones
  pedidas", "Vacaciones sin resolver", "Inicio de vacaciones", "Vacaciones resueltas"), con horario de silencio y
  resúmenes.

Ejemplo de push al empleado:

```json
{"tipo": "vacaciones", "titulo": "Vacaciones aprobadas",
 "cuerpo": "Tus vacaciones del 24/11 al 07/12 y del 04/01 al 10/01 fueron aprobadas (21 días) por Garcia Luis.",
 "datos": {"solicitud_id": "1", "ruta": "/vacaciones/1", "estado": "aprobado", "evento": "aprobada",
           "movimiento_id": "1", "notificacion_id": "2"}}
```

## Guía para Flutter

1. **Pantalla "Pedir vacaciones":**
   - `GET /me/vacaciones/semanas?anio=` (el actual y, desde octubre, también el siguiente).
   - Mostrar un calendario de semanas: solo se tocan las `disponible`.
   - Contar las elegidas contra `saldo.semanas_disponibles`.
   - Mostrar el inicio real (`inicio`, con el aviso de `feriado_lunes`).
2. **Confirmar:** `POST /me/vacaciones/semanas` con los lunes elegidos. Mostrar las `tandas` que devuelve, con las
   fechas reales y los días.
3. **Mis vacaciones:**
   - `GET /me/vacaciones/solicitudes`.
   - "Cancelar" solo con `puede_cancelar`. Si la tanda está aprobada, el texto del botón es "Pedir cancelación".
4. **Mi equipo:** pestaña visible si `GET /me/equipo/vacaciones` devuelve `alcance != "sin_equipo"`.
   - **Pendientes:** `?estado=pendiente`, con el número de pestaña en `por_resolver`.
   - **Calendario:** `/calendario?mes=`.
   - **Saldos:** `/saldos`.
5. **Push:**
   - Al tocar un aviso, abrir `data.ruta` y marcar la notificación con `data.notificacion_id`.
   - `vacaciones_inicio` y `vacaciones_equipo` solo informan.
6. **No hay que calcular fechas ni feriados en la app:** el servidor devuelve todo resuelto.

## Limitaciones

- **Feriados:** dependen del calendario de días no laborables del panel. Si un año no está cargado
  (`feriados_cargados = false`), el inicio no se corre. El panel muestra un aviso en Vacaciones cuando faltan los
  del año actual o, desde octubre, los del siguiente.
- **Días sueltos:** los días que no llegan a una semana completa (proporcional, compensatorios) los carga RR. HH.
  desde el panel.
- **Aprobación en la cadena:** el jefe del jefe ve, pero no aprueba. Recibe el aviso de escalamiento para que pueda
  intervenir.
- **Panel:** RR. HH. aprueba de a una tanda por vez. El aviso al empleado sale por cada tanda resuelta.
- **Datos anteriores:** las vacaciones cargadas antes de 1.53.0 se ven como solicitudes de una sola tanda.
