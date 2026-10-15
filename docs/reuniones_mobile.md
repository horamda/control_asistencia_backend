# Reuniones — contrato para Flutter y web de empleados

Versión de contrato: 1.38.0 · Definición formal: [reuniones_mobile_openapi.yaml](reuniones_mobile_openapi.yaml)

Las reuniones se crean en el panel (Asistencia → Reuniones). Cada una tiene una recurrencia
(diaria, semanal o mensual), un horario, una ventana de registro y una lista de **convocados
obligatorios** (por empleado, sector, puesto o toda la empresa). El empleado registra su asistencia
escaneando el QR de la reunión con la app.

- Base: `/api/v1/mobile/reuniones`. Todas las rutas requieren `Authorization: Bearer <token>` (el mismo JWT del login).
- Fechas `AAAA-MM-DD`; fechas y horas `AAAA-MM-DDTHH:MM:SS-03:00` (hora Argentina). Horas sueltas `HH:MM`.
- Errores: `{"error": "mensaje para mostrar"}` con 400, 401, 403, 404 o 409. El mensaje está listo para el usuario.
- El empleado solo ve las reuniones a las que está convocado.

## Resumen de rutas

| Método | Ruta | Uso en la app |
|---|---|---|
| GET | `/reuniones` | Pantalla "Mis reuniones": definiciones, próxima fecha y mis estadísticas por reunión. |
| GET | `/reuniones/proximas?dias=7` | Inicio ("Reuniones de la semana") y programación de recordatorios locales. |
| POST | `/reuniones/registrar` | Envía el contenido del QR escaneado. |
| GET | `/reuniones/historial?desde=&hasta=&reunion_id=&page=&per=` | Historial de asistencias propias. |
| GET | `/reuniones/estadisticas?desde=&hasta=` | Totales y porcentaje por reunión. |
| GET | `/reuniones/{id}` | Detalle de una reunión con próximas fechas, historial y estadísticas. |

## Estados

Estado de mi asistencia en una fecha (`estado`):

| Valor | Significado | Sugerencia de UI |
|---|---|---|
| `pendiente` | Todavía no abre el registro. | Gris, muestra "Se habilita a las HH:MM". |
| `abierta` | El registro está abierto ahora y no escaneé. | Botón destacado "Escanear QR". |
| `presente` | Registré dentro de la tolerancia. | Verde. |
| `tarde` | Registré después de `tarde_desde`. | Amarillo. |
| `ausente` | No registré y la ventana cerró. | Rojo. |
| `justificado` | Ausencia justificada (vacaciones, franco o RR. HH.). | Gris con el motivo de `observaciones`. |
| `cancelada` | La fecha fue cancelada desde el panel. | Tachado + `motivo_cancelacion`. |

`pendiente` y `abierta` solo aparecen en `/proximas`. `ausente` en `/proximas` es provisorio hasta que el
servidor cierra la reunión (cada 10 minutos); el historial muestra el estado definitivo.

## 1. `GET /reuniones`

```json
{
  "items": [
    {
      "id": 3,
      "nombre": "Reunión de seguridad semanal",
      "descripcion": "Repaso de incidentes, EPP y orden y limpieza.",
      "lugar": "Sala de capacitación",
      "frecuencia": "semanal",
      "dias_semana": [2],
      "mensual_tipo": null,
      "dia_mes": null,
      "semana_mes": null,
      "hora_inicio": "09:00",
      "duracion_min": 45,
      "descripcion_frecuencia": "Todos los miércoles a las 09:00 (45 min)",
      "qr_modo": "ambos",
      "tolerancia_antes_min": 15,
      "tarde_despues_min": 10,
      "cierre_despues_min": null,
      "fecha_inicio": "2026-08-17",
      "fecha_fin": null,
      "proxima_fecha": "2026-10-21",
      "mis_estadisticas": {
        "convocatorias": 9, "presentes": 6, "tarde": 1, "ausentes": 2, "justificados": 0,
        "asistidas": 7, "asistencia_pct": 77.8, "puntualidad_pct": 85.7
      }
    }
  ]
}
```

- `dias_semana`: 0 = lunes … 6 = domingo. En mensual por semana trae un único día.
- `frecuencia`: `diaria` (los días de `dias_semana`), `semanal` (los días de `dias_semana`) o `mensual`.
- Mensual: `mensual_tipo = "dia"` usa `dia_mes` (si el mes es más corto, el último día);
  `mensual_tipo = "semana"` usa `semana_mes` (1 a 4; 5 = última semana) y `dias_semana[0]`.
- Mostrar `descripcion_frecuencia` tal cual; no hace falta reconstruir el texto.
- `cierre_despues_min = null`: el registro cierra cuando termina la reunión.
- `mis_estadisticas` es histórica (todas las fechas). `asistencia_pct` y `puntualidad_pct` pueden ser `null` sin datos.

## 2. `GET /reuniones/proximas?dias=7`

`dias` entre 1 y 31 (por defecto 7), contando desde hoy. Incluye las reuniones de hoy aunque ya hayan pasado.
Orden cronológico.

```json
{
  "desde": "2026-10-15",
  "hasta": "2026-10-21",
  "items": [
    {
      "reunion_id": 5,
      "nombre": "Daily de almacén",
      "lugar": "Dock 2",
      "descripcion": null,
      "fecha": "2026-10-15",
      "inicio": "2026-10-15T07:30:00-03:00",
      "fin": "2026-10-15T07:45:00-03:00",
      "ventana_desde": "2026-10-15T07:15:00-03:00",
      "ventana_hasta": "2026-10-15T07:45:00-03:00",
      "tarde_desde": "2026-10-15T07:35:00-03:00",
      "estado": "presente",
      "cancelada": false,
      "motivo_cancelacion": null,
      "registrado_at": "2026-10-15T07:28:00-03:00",
      "qr_modo": "fijo"
    }
  ]
}
```

### Recordatorios locales (sin push)

1. Al abrir la app, al volver a primer plano y después de registrar, llamar a `/proximas?dias=7`.
2. Cancelar los recordatorios programados por la app y volver a programar uno por cada item con
   `estado` = `pendiente`, `cancelada = false`, en `inicio - 30 minutos` (y opcionalmente otro al abrir `ventana_desde`).
3. Usar `reunion_id` + `fecha` como identificador del recordatorio para no duplicar.
4. Si una fecha se cancela, desaparece del próximo refresco y el recordatorio se elimina en el paso 2.

Las notificaciones push (Firebase) se agregarán en una versión posterior para avisar cambios en el momento.

## 3. `POST /reuniones/registrar`

Body:
```json
{"qr": "fichaya://reunion?t=eyJhbGciOi...", "lat": -34.6037, "lon": -58.3816}
```

- `qr`: el texto escaneado **completo**, sin modificar. También se acepta `qr_token`.
- `lat` / `lon`: opcionales (se guardan como referencia; hoy no se valida distancia).
- Respuestas:
  - `201` primer registro; `200` si ya estaba registrado (`ya_registrado: true`). Ambos con el mismo cuerpo.

```json
{
  "reunion_id": 3,
  "reunion": "Reunión de seguridad semanal",
  "lugar": "Sala de capacitación",
  "fecha": "2026-10-21",
  "inicio": "09:00",
  "fin": "09:45",
  "estado": "presente",
  "registrado_at": "2026-10-21T08:52:10-03:00",
  "ya_registrado": false
}
```

Errores habituales (mostrar `error` tal cual):

| Código | Caso |
|---|---|
| 400 | El texto no es un QR de reunión, QR vencido (el dinámico dura 45 s) o coordenadas inválidas. |
| 403 | No estás convocado a la reunión, o el QR es de otra empresa. |
| 404 | La reunión no existe o está desactivada. |
| 409 | Hoy no hay reunión, todavía no abrió el registro, ya cerró, fecha cancelada, QR impreso reemplazado o QR dinámico de otra fecha. |

### Detección del QR en el escáner

Los QR de reunión empiezan con `fichaya://reunion?`. El escáner único de la app puede derivar:
- empieza con `fichaya://reunion?` → `POST /reuniones/registrar`;
- cualquier otro → flujo actual de fichada (ingreso/egreso).

Si un QR de reunión llega por error al endpoint de fichada, este lo rechaza con el mensaje "Este QR es de una reunión: registrá tu asistencia desde la sección Reuniones." y no genera ninguna marca.

## 4. `GET /reuniones/historial`

Parámetros opcionales: `desde`, `hasta` (por defecto, el último año), `reunion_id`, `page` (1), `per` (20, máx. 100).

```json
{
  "items": [
    {"id": 812, "reunion_id": 3, "nombre": "Reunión de seguridad semanal", "lugar": "Sala de capacitación",
     "fecha": "2026-10-14", "inicio": "09:00", "fin": "09:45", "estado": "tarde",
     "registrado_at": "2026-10-14T09:12:00-03:00", "metodo": "qr_fijo", "observaciones": null}
  ],
  "page": 1, "per_page": 20, "total": 1
}
```

`metodo`: `qr_fijo`, `qr_dinamico`, `manual` (cargado por RR. HH.) o `sistema` (ausencia/justificación del cierre automático).

## 5. `GET /reuniones/estadisticas?desde=&hasta=`

Por defecto, los últimos 90 días. Rango máximo 366 días. No cuenta fechas canceladas.

```json
{
  "periodo": {"desde": "2026-07-18", "hasta": "2026-10-15"},
  "totales": {"convocatorias": 20, "presentes": 15, "tarde": 2, "ausentes": 2, "justificados": 1,
              "asistidas": 17, "asistencia_pct": 89.5, "puntualidad_pct": 88.2},
  "por_reunion": [
    {"reunion_id": 3, "nombre": "Reunión de seguridad semanal", "convocatorias": 9, "presentes": 6, "tarde": 1,
     "ausentes": 2, "justificados": 0, "asistidas": 7, "asistencia_pct": 77.8, "puntualidad_pct": 85.7}
  ]
}
```

- `asistencia_pct` = asistidas / (convocatorias − justificados) × 100.
- `puntualidad_pct` = presentes / asistidas × 100.

## 6. `GET /reuniones/{id}`

Mismo objeto que en `/reuniones` más:
- `activa` (bool; una reunión desactivada sigue visible para consultar el historial),
- `proximas_fechas`: hasta 6 fechas (`AAAA-MM-DD`) de los próximos 60 días, desde hoy,
- `historial`: las últimas 10 asistencias propias (formato del punto 4),
- `mis_estadisticas`: los últimos 90 días de esa reunión (formato de `por_reunion`) o `null`.

404 si no existe o el empleado no está convocado.

## Reglas del negocio (para mensajes y pantallas)

- Ventana de registro: desde `tolerancia_antes_min` antes del inicio hasta el cierre (`cierre_despues_min`
  desde el inicio, o el fin de la reunión). Tarde: después de `tarde_despues_min`.
- Al cerrar la ventana, el servidor marca **ausente** a los convocados sin registro y **justificado** a quienes
  tenían vacaciones o franco ese día. RR. HH. puede corregir cualquier estado desde el panel.
- QR fijo: impreso en la sala; si se regenera, el anterior deja de funcionar. QR dinámico: se proyecta desde el
  panel, cambia cada 20 s y vale 45 s. `qr_modo` indica cuál acepta la reunión (`fijo`, `dinamico`, `ambos`).
- Las reuniones terminan el mismo día (no cruzan medianoche).
