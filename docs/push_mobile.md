# Notificaciones push — contrato para Flutter (Android) y la app web

Versión de contrato: 1.47.0 · Firebase Cloud Messaging (FCM). Solo **Android** y **web**; iOS queda fuera.

El backend envía los avisos; la app solo tiene que registrar su token y abrir la pantalla correcta al tocar
la notificación. Si Firebase no está configurado en el servidor, `GET /push/config` devuelve `activo: false`
y la app no debe pedir permisos ni registrar nada.

## Estado (1.43.1): activo en producción

Desde 1.43.1 Firebase está configurado en producción y `GET /push/config` devuelve `activo: true`. El
servidor ya envía los avisos de reuniones y el recordatorio de 30 minutos a todo dispositivo registrado.
Lo que falta está del lado de la app: registrar el token (ver abajo).

| Dato | Valor |
|---|---|
| Proyecto Firebase | `fichaya-917d5` (número `885761435547`) |
| App Android | paquete `com.controlasistencia.ficharqr` · app id `1:885761435547:android:ae0ecbecd145bfcdcfe33e` |
| App web | app id `1:885761435547:web:d9d260b374b68eeccfe33e` |
| Canal Android | `reuniones` |
| URL que abre la notificación web | `https://controlasistenciafrontend-production-30a5.up.railway.app` + `ruta` |

La configuración web completa (`apiKey`, `authDomain`, `projectId`, `storageBucket`, `messagingSenderId`,
`appId`) y la clave VAPID llegan en `GET /push/config`. Son datos públicos (van dentro de la app web); la
credencial privada del servidor nunca sale del backend.

## Rutas

Base `/api/v1/mobile/push`, con `Authorization: Bearer <token>` como el resto de la API.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/push/config` | `{activo, web, vapid_key, canal_android}`. Llamar después del login. |
| POST | `/push/dispositivo` | Registrar o actualizar el token: `{token, plataforma: "android"|"web", app_version}`. |
| DELETE | `/push/dispositivo` | Al cerrar sesión: `{token}`. El dispositivo deja de recibir avisos de ese empleado. |

```json
GET /push/config
{"activo": true, "canal_android": "fichaya", "vapid_key": "BF2u4_…",
 "web": {"apiKey": "AIza…", "authDomain": "fichaya-917d5.firebaseapp.com", "projectId": "fichaya-917d5",
         "storageBucket": "fichaya-917d5.firebasestorage.app", "messagingSenderId": "885761435547",
         "appId": "1:885761435547:web:d9d260b374b68eeccfe33e"}}
```

- `POST /dispositivo` responde `{"registrado": true, "activo": true}`. 400 `{"error": "…"}` si el token
  (20 a 1024 caracteres) o la plataforma son inválidos.
- `DELETE /dispositivo` responde `{"quitado": true|false}`.
- Llamar a `POST /dispositivo` **después del login**, **cada vez que FCM renueva el token** (`onTokenRefresh`) y al
  abrir la app (es idempotente: actualiza `ultimo_uso`). Si el mismo teléfono lo usa otro empleado, el token pasa
  al empleado logueado.

## Android (Flutter)

Ya hecho en el repo de Flutter: `android/app/google-services.json` y el plugin
`com.google.gms.google-services` (4.5.0) en `settings.gradle.kts` y `app/build.gradle.kts`. La app compila.

Falta:
1. Paquetes `firebase_core`, `firebase_messaging` y `flutter_local_notifications` (para mostrar avisos con la
   app abierta). `Firebase.initializeApp()` en `main()` antes de `runApp`.
2. Crear el canal **`fichaya`** (importancia alta, sonido `res/raw/fichaya`) al iniciar. El backend lo usa en
   todos los avisos desde 1.46.0 (antes `reuniones`); sin el canal, Android 8+ usa el canal por defecto del
   manifest. Ver [sonido propio](#sonido-propio-de-fichaya-146).
3. Android 13+: `FirebaseMessaging.instance.requestPermission()` (pide `POST_NOTIFICATIONS`; declararlo en el
   `AndroidManifest.xml`).
4. Tras el login, si `config.activo`: `getToken()` → `POST /push/dispositivo` con `plataforma: "android"`.
   Escuchar `onTokenRefresh` y repetir el POST.
5. Handler de segundo plano (`FirebaseMessaging.onBackgroundMessage`, función top-level) aunque no haga nada:
   la notificación la muestra el sistema porque el mensaje trae `notification`.

### Acuses: recibido y abierto (1.47.0)

Cada push trae `data.envio_id` y `data.acuse` (firma). La app avisa al servidor:

```http
POST /api/v1/mobile/push/acuse        (sin Authorization)
{"envio_id": "41", "acuse": "<data.acuse>", "evento": "recibido" | "abierto"}
→ 200 {"ok": true}   ·   403 {"error": "Acuse inválido."}   ·   400 si falta algo
```

- **`recibido`**: apenas llega el mensaje, en primer plano (`onMessage`) y en el manejador de segundo plano
  (`onBackgroundMessage`, que en Android corre aunque la app esté cerrada). No lleva JWT a propósito: en segundo
  plano no hay sesión. La firma impide marcar envíos ajenos.
- **`abierto`**: al tocar la notificación (`onMessageOpenedApp` y `getInitialMessage`). Abierto implica recibido.
- Es idempotente (queda la primera hora) y no debe bloquear nada: si falla, se ignora sin reintentos.
- El panel muestra «Recibido» / «Abierto» en Avisos automáticos y en el detalle de cada comunicado. Un aviso
  «Enviado» sin acuse puede no haber llegado o la app no pudo confirmarlo (cerrada a la fuerza, ahorro de batería).

### Sonido propio de FichaYa (1.46.0)

Los avisos suenan con un tono propio (`android/app/src/main/res/raw/fichaya.wav`, menos de 1 s):

- El backend manda `android.notification.channel_id = "fichaya"` y `android.notification.sound = "fichaya"`
  (este último solo lo usa Android 7 o anterior).
- En Android 8+ el sonido es del **canal** y queda fijo al crearlo: la app crea el canal `fichaya`
  (`AndroidNotificationChannel(..., sound: RawResourceAndroidNotificationSound('fichaya'))`) y usa el mismo
  canal para los avisos con la app abierta y los recordatorios locales. Para cambiar el tono más adelante hay
  que crear otro canal (p. ej. `fichaya_v2`) y cambiar `CANAL_ANDROID` en el backend.
- `res/raw/keep.xml` conserva `@raw/fichaya` para que el shrinker del build release no lo borre.
- `default_notification_channel_id` del manifest pasa a `fichaya`.
- El usuario puede cambiar o silenciar el sonido desde Ajustes → Apps → FichaYa → Notificaciones.
- **Web**: los navegadores no permiten sonidos propios en las notificaciones; suena el del sistema.

## Web (Flutter web)

1. Inicializar Firebase con el objeto `web` de `GET /push/config` (o los mismos valores compilados en
   `firebase_options.dart`, por ejemplo con `flutterfire configure`).
2. Servir `web/firebase-messaging-sw.js` en la raíz del sitio. Un service worker no puede llamar a la API con el
   token del usuario, así que lleva la configuración escrita:

   ```js
   importScripts('https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js');
   importScripts('https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging-compat.js');
   firebase.initializeApp({ /* mismo objeto "web" de GET /push/config */ });
   firebase.messaging();  // muestra las notificaciones con la app cerrada
   ```
3. `requestPermission()` (el navegador pregunta) y `getToken(vapidKey: config.vapid_key)` → `POST /push/dispositivo`
   con `plataforma: "web"`.
4. Requiere **HTTPS** (producción lo es). Al tocar la notificación con la app cerrada, el navegador abre
   `https://controlasistenciafrontend-production-30a5.up.railway.app` + `ruta`, así que la app web tiene que
   resolver la ruta `/reuniones/{id}` al cargar.

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
| `salida_pendiente` (1.44.0) | La jornada de hoy sigue abierta 30 min después de la salida prevista (una vez por jornada) | `asistencia_id`, `fecha`, `ruta` = `/asistencia` |
| `epp_resuelto` (1.44.0) | Pedido de EPP aprobado, aprobado con menos unidades o rechazado | `pedido_id`, `estado`, `ruta` = `/epp/{id}` |
| `epp_entregado` (1.44.0) | Entrega parcial o completa registrada | `pedido_id`, `estado` (`parcial`/`entregado`), `ruta` = `/epp/{id}` |
| `reintegro` (1.44.0) | Rendición de viáticos aprobada, rechazada, devuelta para corregir o pagada | `solicitud_id`, `estado`, `ruta` = `/reintegros/{id}` |
| `reintegro_recordatorio` (1.44.0) | Día 5: completar los viáticos del mes anterior (mismo texto que `/reintegros/recordatorios`) | `periodo`, `ruta` = `/reintegros` |
| `adelanto` (1.44.0) | Adelanto aprobado o rechazado | `adelanto_id`, `estado`, `ruta` = `/adelantos` |
| `pedido_mercaderia` (1.44.0) | Pedido de mercadería aprobado o rechazado | `pedido_id`, `estado`, `ruta` = `/pedidos-mercaderia` |
| `comunicado` (1.44.0) | Comunicado enviado desde el panel | `comunicado_id`, `ruta` = `/comunicados/{id}`, `imagen` (1.45.0, solo si tiene imagen) |

Desde 1.47.0 **todos** los tipos traen además `envio_id` y `acuse` (ver [acuses](#acuses-recibido-y-abierto-1470)).

- `ruta` identifica la pantalla a abrir; la app la traduce a su navegación (no hace falta que exista como ruta
  con nombre). Al tocar la notificación: navegar a esa pantalla (`onMessageOpenedApp` y `getInitialMessage`).
  En la web, `FRONTEND_WEB_URL + ruta` es la URL que abre el navegador.
- Sugerencia de pantallas: `/asistencia` → inicio/fichada; `/epp/{id}` → detalle del pedido de EPP;
  `/reintegros/{id}` → detalle de la rendición; `/adelantos` y `/pedidos-mercaderia` → sus listados;
  `/comunicados/{id}` → el comunicado (abrirlo con `GET /comunicados/{id}`, que lo marca leído).
- Con la app abierta (`onMessage`), mostrar un aviso dentro de la app y refrescar la pantalla afectada
  (`/reuniones/proximas`, la bandeja de comunicados, el pedido, etc.).
- Un `tipo` desconocido se ignora sin error (pueden sumarse tipos nuevos).

### Notificaciones con imagen

Desde 1.45.0 un comunicado con imagen llega con `notification.image` (y la misma URL en `data.imagen`):

- **Android**: con la app cerrada o en segundo plano, el sistema muestra la miniatura a la derecha y la imagen
  grande al expandir la notificación (estilo *big picture*). No hace falta código.
- **Web**: el navegador la muestra grande (Chrome en Windows/Android; macOS solo muestra el texto).
- **App abierta** (`onMessage`): Firebase no muestra nada; si la app arma su aviso local
  (p. ej. `flutter_local_notifications`), puede descargar `data.imagen` y usar `BigPictureStyleInformation`.
- La imagen de la notificación es una versión **2:1 (1024 × 512)** que arma el servidor: la imagen entera
  centrada sobre un fondo desenfocado de ella misma (desde 1.46.0). Android la recorta al centro si no es 2:1,
  así que un afiche cuadrado o vertical ya no pierde el texto. La de la app (`imagen_url`) es la original.
- La URL es pública y firmada, y **vence a los 7 días**: sirve para la notificación, no para guardarla. Dentro
  de la app usar `imagen_url` del comunicado (con JWT).

## Recordatorios: push y avisos locales

Con push activo, el **recordatorio de 30 minutos lo envía el servidor**. Para no duplicar:
- Android: si `config.activo` es `true`, no programar el recordatorio local de 30 min (sí se pueden mantener otros
  avisos locales que la app quiera). Si es `false`, seguir con el recordatorio local.
- Web: no hay avisos locales; el push es la única vía.

## Cómo probar

1. Iniciar sesión en la app (Android o web) y aceptar las notificaciones.
2. En el panel: **Sistema → Notificaciones push** debe decir *Conectado* y listar el dispositivo.
3. Elegir el empleado y tocar **Enviar prueba**: llega `tipo: "prueba"` en unos segundos.
