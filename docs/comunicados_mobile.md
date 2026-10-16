# Comunicados — contrato para Flutter (Android y web)

Versión de contrato: 1.45.0

RR. HH. envía comunicados desde el panel (Personal → Comunicados) a toda la empresa, a sectores, puestos,
personas puntuales y/o sucursales. A cada destinatario le llega una notificación push (`data.tipo = "comunicado"`)
y el comunicado queda en su **bandeja** dentro de la app. El panel muestra quién lo leyó.

## Rutas

Base `/api/v1/mobile/comunicados`, con `Authorization: Bearer <token>`.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/comunicados?page=1` | Bandeja del empleado (20 por página, el más nuevo primero) y cantidad sin leer. |
| GET | `/comunicados/{id}` | Un comunicado. **Lo marca como leído** (la primera vez queda la fecha). |
| POST | `/comunicados/{id}/leido` | Marca leído sin abrir el detalle (misma respuesta que el GET). |
| POST | `/comunicados/leer-todos` | Marca todos como leídos: `{"marcados": 3}`. |
| GET | `/comunicados/{id}/imagen` | Imagen del comunicado (JPEG). No lo marca como leído. 1.45.0 |

```json
GET /comunicados
{"items": [{"id": 12, "titulo": "Corte de luz", "mensaje": "El jueves no hay luz.\nTraigan linterna.",
            "imagen_url": "/api/v1/mobile/comunicados/12/imagen",
            "fecha": "2026-10-16T09:30:15", "leido": false, "leido_at": null}],
 "no_leidos": 1, "total": 1, "page": 1, "pages": 1}

GET /comunicados/12
{"id": 12, "titulo": "Corte de luz", "mensaje": "…", "imagen_url": "/api/v1/mobile/comunicados/12/imagen",
 "fecha": "2026-10-16T09:30:15", "leido": true, "leido_at": "2026-10-16T10:02:41"}
```

- 404 `{"error": "Comunicado no encontrado."}` si no existe, se quitó o no era para este empleado.
- `mensaje` es texto plano (hasta 2000 caracteres) con saltos de línea: mostrarlo respetándolos.
  La notificación push trae solo el comienzo (180 caracteres).
- `imagen_url` (1.45.0): `null` si el comunicado no tiene imagen. Es relativa a la base de la API y pide el mismo
  `Authorization: Bearer` (en Flutter: `Image.network(base + imagen_url, headers: {...})`). JPEG ajustado al
  celular sin recortar: hasta 1080 px de ancho y 1920 px de alto (desde 1.46.0; antes hasta 1800 px de lado).
  Mostrarla debajo del título con el ancho de la pantalla y la altura proporcional (`BoxFit.fitWidth`), sin
  recortarla: suelen ser afiches con texto. En la lista alcanza con una miniatura o un ícono.
- Si RR. HH. lo quita desde el panel, desaparece de la bandeja (la notificación ya enviada no se puede retirar).
- Los destinatarios se fijan al enviar: un empleado que ingresa después no ve comunicados anteriores.

## En la app

1. Pantalla **Comunicados** con la lista; los no leídos resaltados. Badge con `no_leidos` en el menú o en el inicio.
2. Al abrir uno: `GET /comunicados/{id}` (lo marca leído) y refrescar el badge.
3. Push `comunicado` (`data.comunicado_id`, `data.ruta = /comunicados/{id}`): al tocarla, abrir ese comunicado.
   Con la app abierta (`onMessage`), refrescar la bandeja y el badge.
   Si el comunicado tiene imagen, la notificación la trae en `notification.image` y Android/web la muestran
   solos (miniatura que se agranda al expandir). Ver [push con imagen](push_mobile.md#notificaciones-con-imagen).
4. Sin push (permiso denegado o Firebase inactivo) la bandeja funciona igual: consultar `GET /comunicados` al
   abrir la app o el inicio.
