# Notificaciones push — contrato para Flutter (Android) y la app web

Versión de contrato: 1.53.0 · Firebase Cloud Messaging (FCM). Solo **Android** y **web**; iOS queda fuera.

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
{"activo": true, "canal_android": "fichaya", "canal_android_urgente": "fichaya_urgente", "vapid_key": "BF2u4_…",
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

### Configuración por empresa y resúmenes (1.49.0)

RR. HH. configura en el panel (Comunicados → Configuración de avisos) qué avisos salen, a quién, cuándo y sus
tiempos, más un horario de silencio. Para la app no cambia nada, salvo dos cosas:

- Un aviso puede llegar **más tarde** que el hecho (horario de silencio o resumen). La pantalla a abrir sigue en `ruta`.
- **Resumen**: varias solicitudes del mismo horario llegan en **un solo push** («Tenés 3 solicitudes para revisar»)
  con `data.cantidad` y la `ruta`/`envio_id`/`acuse` de la primera. El acuse de ese push vale para todas.

### Vibración y canal de urgentes (1.50.0)

La app crea **dos canales** (en Android 8+ el sonido y la vibración quedan fijos al crearlos):

| Canal | Para | Importancia | Vibración (ms: espera, vibra, pausa…) |
|---|---|---|---|
| `fichaya` — «Avisos de FichaYa» | todo lo demás | alta | `[0, 180, 120, 180]` (dos pulsos cortos) |
| `fichaya_urgente` — «Avisos urgentes de FichaYa» | `salida_pendiente` y `recordatorio` (reunión por empezar) | máxima | `[0, 450, 200, 450, 200, 450]` (tres largos) |

- Los dos con el tono `res/raw/fichaya`. El backend elige el canal por `data.tipo` y manda los mismos patrones en
  `vibrate_timings` para Android 7 o anterior. `GET /push/config` devuelve `canal_android_urgente`.
- Con la app abierta y en los recordatorios locales de reunión, la app usa el mismo criterio.
- El permiso `VIBRATE` lo declara `flutter_local_notifications`. En modo silencio o No molestar el sistema no vibra.
- Una app vieja sin `fichaya_urgente` recibe esos avisos en el canal por defecto del manifest.

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
| `ingreso_pendiente` (1.54.0) | Tiene horario hoy y no fichó el ingreso 15 min después de la hora prevista (configurable). Una vez por día. No sale con licencia, justificación aprobada, vacaciones, franco, feriado ni terminado el horario. Solo push | `fecha`, `empleado_id`, `ruta` = `/asistencia` |
| `ingreso_equipo` (1.54.0) | Al jefe directo (si la regla lo incluye): alguien de su equipo no fichó el ingreso. Solo push | `fecha`, `empleado_id` |
| `epp_resuelto` (1.44.0) | Pedido de EPP aprobado, aprobado con menos unidades o rechazado | `pedido_id`, `estado`, `ruta` = `/epp/{id}` |
| `epp_entregado` (1.44.0) | Entrega parcial o completa registrada | `pedido_id`, `estado` (`parcial`/`entregado`), `ruta` = `/epp/{id}` |
| `reintegro` (1.44.0) | Rendición de viáticos aprobada, rechazada, devuelta para corregir o pagada | `solicitud_id`, `estado`, `ruta` = `/reintegros/{id}` |
| `reintegro_recordatorio` (1.44.0) | Día 5: completar los viáticos del mes anterior (mismo texto que `/reintegros/recordatorios`) | `periodo`, `ruta` = `/reintegros` |
| `adelanto` (1.44.0) | Adelanto aprobado o rechazado | `adelanto_id`, `estado`, `ruta` = `/adelantos` |
| `pedido_mercaderia` (1.44.0) | Pedido de mercadería aprobado o rechazado | `pedido_id`, `estado`, `ruta` = `/pedidos-mercaderia` |
| `justificacion` (1.48.0) | Justificación aprobada o rechazada (con el motivo) | `justificacion_id`, `estado`, `ruta` = `/justificaciones` |
| `vacaciones` (1.48.0) | Vacaciones, compensatorio o ajuste aprobado o rechazado. Desde 1.53.0, las vacaciones van por solicitud: `evento` = `aprobada`, `rechazada`, `cancelada`, `cancelacion_rechazada` o `cargada` (por RR. HH.) | `movimiento_id`, `estado`; 1.53.0: `solicitud_id`, `evento`, `ruta` = `/vacaciones/{solicitud_id}` |
| `vacaciones_inicio` (1.53.0) | Al empleado, el día hábil anterior a que empiecen sus vacaciones. Solo push | `solicitud_id`, `movimiento_id`, `ruta` = `/vacaciones/{solicitud_id}` |
| `vacaciones_equipo` (1.53.0) | Al jefe (si la regla lo incluye): alguien de su equipo sale de vacaciones al día siguiente hábil. Solo push | `solicitud_id`, `movimiento_id`, `ruta` = `/equipo/vacaciones/{solicitud_id}` |
| `feedback_asignado` (1.48.0) | Al responsable: tiene un feedback nuevo para resolver | `feedback_id`, `ruta` = `/feedback/{id}` |
| `feedback_resuelto` (1.48.0) | Al que lo cargó: su feedback se resolvió | `feedback_id`, `ruta` = `/feedback/{id}` |
| `trivia_nueva` (1.48.0) | Se abrió una trivia (a quien todavía no jugó) | `trivia_id`, `ruta` = `/trivia/{id}` |
| `trivia_recordatorio` (1.48.0) | Quedan 24 h o 2 h para participar (a quien todavía no jugó) | `trivia_id`, `ruta` = `/trivia/{id}` |
| `revision_pendiente` (1.48.0) | Para revisar: un empleado envió una justificación, vacaciones, adelanto, pedido de mercadería, viáticos, EPP o (1.49.0) un reporte de seguridad. Va al jefe directo, a RR. HH. y/o al responsable de Seguridad e Higiene según la configuración de la empresa | `modulo` (`seguridad_higiene` para reportes), `registro_id`, `ruta` = `/revisiones/{modulo}`; en un resumen, `cantidad` |
| `seguridad_resultado` (1.49.0) | A quien reportó: su reporte de seguridad fue aprobado o rechazado (con motivo) | `evento_id`, `estado`, `ruta` = `/seguridad/{evento_id}` |
| `seguridad_accion` (1.49.0) | Al responsable de una acción correctiva: asignada, por vencer y vencida | `accion_id`, `evento_id`, `ruta` = `/seguridad/{evento_id}` |
| `comunicado` (1.44.0) | Comunicado enviado desde el panel | `comunicado_id`, `ruta` = `/comunicados/{id}`, `imagen` (1.45.0, solo si tiene imagen) |

Desde 1.47.0 **todos** los tipos traen además `envio_id` y `acuse` (ver [acuses](#acuses-recibido-y-abierto-1470)).

Desde 1.53.0 `revision_pendiente` de vacaciones es uno por solicitud, con `solicitud_id`, `ruta` = `/equipo/vacaciones/{solicitud_id}` y `evento` (`cancelacion` cuando piden cancelar unas aprobadas, `escalada` cuando sigue sin resolver cerca del inicio). Ver [vacaciones](vacaciones_mobile.md#avisos-push-y-bandeja).

Desde 1.51.0 los avisos que quedan en la bandeja traen `notificacion_id`: al tocarlo, marcarla con
`POST /me/notificaciones/{notificacion_id}/leer`. No lo traen los recordatorios (`recordatorio`, `salida_pendiente`,
`trivia_recordatorio`, `reintegro_recordatorio`, `seguridad_accion` por vencer), la `prueba` ni un resumen de
varios avisos. Recibir el push no es leer. Ver [bandeja de notificaciones](notificaciones_mobile.md).

- `ruta` identifica la pantalla a abrir; la app la traduce a su navegación (no hace falta que exista como ruta
  con nombre). Al tocar la notificación: navegar a esa pantalla (`onMessageOpenedApp` y `getInitialMessage`).
  En la web, `FRONTEND_WEB_URL + ruta` es la URL que abre el navegador.
- Sugerencia de pantallas: `/asistencia` → inicio/fichada; `/epp/{id}` → detalle del pedido de EPP;
  `/reintegros/{id}` → detalle de la rendición; `/adelantos` y `/pedidos-mercaderia` → sus listados;
  `/comunicados/{id}` → el comunicado (abrirlo con `GET /comunicados/{id}`, que lo marca leído).
- Con la app abierta (`onMessage`), mostrar un aviso dentro de la app y refrescar la pantalla afectada
  (`/reuniones/proximas`, la bandeja de comunicados, el pedido, etc.).
- Un `tipo` desconocido se ignora sin error (pueden sumarse tipos nuevos).
- `revision_pendiente` llega a los usuarios del panel **vinculados a un empleado** (Usuarios → empleado) con
  permiso de aprobar ese módulo, en la app de ese empleado. No hay pantalla de aprobación en la app: alcanza
  con mostrar la notificación (se aprueba en el panel). Nunca le llega al mismo que hizo la solicitud.
- Desde 1.48.0 todo aviso al empleado sale por push. Las bandejas de la app (comunicados, recordatorios de
  viáticos, `/trivia/notificaciones`) siguen funcionando igual para quien no tiene las notificaciones activadas.

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
