# Notificaciones push — contrato para Flutter (Android) y la app web

Versión de contrato: 1.43.0 · Firebase Cloud Messaging (FCM). Solo **Android** y **web**; iOS queda fuera.

El backend envía los avisos; la app solo tiene que registrar su token y abrir la pantalla correcta al tocar
la notificación. Mientras Firebase no esté configurado en el servidor, `GET /push/config` devuelve
`activo: false` y la app no debe pedir permisos ni registrar nada.

## Rutas

Base `/api/v1/mobile/push`, con `Authorization: Bearer <token>` como el resto de la API.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/push/config` | `{activo, web, vapid_key, canal_android}`. Llamar al iniciar sesión. |
| POST | `/push/dispositivo` | Registrar o actualizar el token: `{token, plataforma: "android"|"web", app_version}`. |
| DELETE | `/push/dispositivo` | Al cerrar sesión: `{token}`. El dispositivo deja de recibir avisos de ese empleado. |

```json
GET /push/config
{"activo": true, "canal_android": "reuniones", "vapid_key": "BKx…",
 "web": {"apiKey": "…", "authDomain": "…", "projectId": "fichaya-…", "messagingSenderId": "…", "appId": "…"}}
```

- `POST /dispositivo` responde `{"registrado": true, "activo": true}`. 400 si el token o la plataforma son inválidos.
- Llamar a `POST /dispositivo` **después del login**, **cada vez que FCM renueva el token** (`onTokenRefresh`) y al
  abrir la app (es idempotente: actualiza `ultimo_uso`). Si el mismo teléfono lo usa otro empleado, el token pasa
  al empleado logueado.

## Android (Flutter)

1. Paquetes: `firebase_core`, `firebase_messaging` (y `flutter_local_notifications` para mostrar avisos con la app abierta).
2. `google-services.json` en `android/app/` (lo genera Firebase al registrar la app Android).
3. Crear el canal de notificaciones **`reuniones`** (importancia alta) al iniciar la app. El backend lo usa en todos los avisos.
4. Android 13+: pedir el permiso `POST_NOTIFICATIONS` (`FirebaseMessaging.instance.requestPermission()`).
5. `getToken()` → `POST /push/dispositivo` con `plataforma: "android"`.

## Web (Flutter web)

1. Inicializar Firebase con el objeto `web` de `GET /push/config` (o el mismo valor compilado en la app).
2. Servir `web/firebase-messaging-sw.js` (service worker de FCM) en la raíz del sitio, con la misma configuración.
3. `requestPermission()` (el navegador pregunta) y `getToken(vapidKey: config.vapid_key)` → `POST /push/dispositivo`
   con `plataforma: "web"`.
4. Requiere **HTTPS**. Al tocar la notificación con la app cerrada, el navegador abre `FRONTEND_WEB_URL + ruta`.

## Contenido de cada aviso

Todos traen `notification` (título y texto listos para mostrar) y `data` con strings:

| `data.tipo` | Cuándo | Otros campos |
|---|---|---|
| `reunion_nueva` | Se creó una reunión a la que está convocado | `reunion_id`, `ruta` |
| `reunion_cambio` | Cambió horario, días o lugar | `reunion_id`, `ruta` |
| `reunion_cancelada` / `reunion_reactivada` | Se canceló o reactivó una fecha | `reunion_id`, `fecha`, `ruta` |
| `reunion_horario` | Cambió el horario de una fecha | `reunion_id`, `fecha`, `ruta` |
| `recordatorio` | 30 min antes, si todavía no registró | `reunion_id`, `fecha`, `ruta` |
| `prueba` | Botón "Enviar prueba" del panel | `ruta` |

- `ruta` es la pantalla a abrir (`/reuniones/{id}`). Al tocar la notificación: navegar a esa ruta
  (`onMessageOpenedApp` y `getInitialMessage`).
- Con la app abierta (`onMessage`), mostrar un aviso dentro de la app y refrescar `/reuniones/proximas`.

## Recordatorios: push y avisos locales

Con push activo, el **recordatorio de 30 minutos lo envía el servidor**. Para no duplicar:
- Android: si `config.activo` es `true`, no programar el recordatorio local de 30 min (sí se pueden mantener otros
  avisos locales que la app quiera).
- Web: no hay avisos locales; el push es la única vía.
