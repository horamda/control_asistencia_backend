# Contrato de validación de carga para frontend web y Flutter

Versión documental: **1.30.1**, 2026-09-29. Compatible con la API de cargas 1.30.0; esta revisión no cambia endpoints ni comportamiento del servidor.

Fuentes: `routes/carga_routes.py`, `services/carga_service.py`, `repositories/carga_repository.py`. Esquema procesable: [mobile_v1_openapi.yaml](mobile_v1_openapi.yaml). Operación y migración: [validacion_carga.md](validacion_carga.md).

## URL y autenticación

Base local: `http://localhost:5000/api/v1/mobile`. Base de producción: `https://control-asistencia.up.railway.app/api/v1/mobile`. Los paths de este documento se agregan a esa base **una sola vez**, sin barra final en `/cargas`.

Todos los endpoints de cargas requieren `Authorization: Bearer <token>` del empleado, incluyendo las fotos. Reutilizar el login y la renovación de sesión existentes. En navegador no se utiliza la cookie del panel administrativo para esta API. El origen web debe estar permitido en `CORS_ALLOWED_ORIGINS` del backend; no usar `mode: no-cors`.

Documentar una URL de producción no garantiza que la versión esté desplegada. Publicar backend y aplicar su migración antes de habilitar el frontend. Un 404 en `/cargas/config` significa que no se pudo obtener la configuración; no interpretarlo como una lista vacía ni como una validación guardada.

## Endpoints

| Método | Path | Respuesta |
|---|---|---|
| GET | `/cargas/config` | 200: disponibilidad, vehículos, horarios y límites |
| POST | `/cargas` | 201: nueva validación; 200: mismo envío ya registrado |
| GET | `/cargas?page=1` | 200: historial propio paginado |
| GET | `/cargas/{id}` | 200: detalle propio con IDs de fotos |
| GET | `/cargas/fotos/{id}` | 200: binario JPEG privado |

No existen endpoints móviles de edición/eliminación de validaciones ni CRUD JSON de camiones/horarios. Esos catálogos se administran en el panel web con sesión y CSRF, como se detalla al final.

## Configuración y acceso al módulo

Ejemplo de `GET /cargas/config`:

```json
{
  "habilitado": true,
  "tiene_historial": false,
  "camiones": [
    {"id": 7, "numero": "014", "patente": "AA123BB", "sucursal_id": 2, "sucursal_nombre": "Depósito", "tiene_inicial": 0}
  ],
  "horarios": [
    {"id": 1, "nombre": "Carga inicial", "tipo": "inicial", "sucursal_id": null, "desde_minuto": 0, "hasta_minuto": 485},
    {"id": 2, "nombre": "Recarga", "tipo": "recarga", "sucursal_id": null, "desde_minuto": 660, "hasta_minuto": 1440}
  ],
  "fecha_servidor": "2026-09-29T07:55:12-03:00",
  "zona_horaria": "America/Argentina/Buenos_Aires",
  "max_fotos": 5,
  "max_foto_bytes": 5242880
}
```

- Mostrar el acceso cuando `habilitado === true || tiene_historial === true`.
- Permitir el formulario solo con `habilitado === true`. Un empleado activo que pierde el puesto habilitado conserva su historial. Si no está habilitado, `camiones` y `horarios` vienen vacíos.
- La habilitación la decide el backend según los puestos configurados, principal o adicionales activos. No deducirla por nombre de puesto, rol del panel ni un dato guardado en el dispositivo.
- `camiones` contiene vehículos activos de la empresa del empleado. `tiene_inicial` indica si ese camión ya tiene carga inicial hoy, registrada por cualquier empleado. No debe calcularse a partir del historial propio.
- Sugerir `inicial` cuando `tiene_inicial === 0` y `recarga` cuando sea `1`. Es una sugerencia: otro empleado puede registrar mientras el formulario está abierto; el servidor vuelve a comprobarlo.
- Si no hay vehículos, mostrar “No hay vehículos activos”. Si no hay regla aplicable, informar la falta de configuración. No inventar un horario en el cliente.
- Actualizar configuración al abrir el módulo, cambiar de día y después de registrar o recibir un conflicto. Nunca usar un resultado en caché para dar por válida una operación.

### Elección del horario

1. Filtrar `horarios` por el `tipo` seleccionado.
2. Buscar la regla cuyo `sucursal_id` coincida con la **sucursal del camión seleccionado**.
3. Si no existe, utilizar la regla general con `sucursal_id: null`.
4. Debe quedar exactamente una regla aplicable. El servidor responde 409 si falta o es ambigua.

Los valores son minutos desde medianoche, no segundos. Inicio **inclusive**, fin **exclusivo**; `1440` representa fin del día. La configuración inicial es `[00:00,08:05)` y `[11:00,24:00)`. No fijar esos valores en el frontend: pueden modificarse desde el CRUD.

La hora del servidor al registrar determina `en_horario`; la hora del teléfono y `fecha_servidor` de una consulta anterior son solo referencias visuales. Una validación inicial a las 08:05 queda fuera de horario; una recarga a las 11:00 queda en horario con la configuración inicial.

## Alta JSON sin fotos

```http
POST /api/v1/mobile/cargas
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "camion_id": 7,
  "tipo": "inicial",
  "consolidado": "000123",
  "valida": true,
  "observaciones": "",
  "envio_id": "08271a75-ff73-479e-9304-5e9f949330f7",
  "origen": "web"
}
```

| Campo | Tipo recomendado | Regla |
|---|---|---|
| `camion_id` | entero positivo | Obligatorio; seleccionar del catálogo recibido |
| `tipo` | string | Obligatorio: `inicial` o `recarga` |
| `consolidado` | string | Obligatorio, 1–64 caracteres; preservar ceros iniciales; servidor recorta espacios y pasa a mayúsculas |
| `valida` | boolean | Obligatorio; selección explícita Sí/No, sin valor inicial automático |
| `observaciones` | string | Hasta 2.000 caracteres; obligatorio y no vacío si `valida` es false |
| `envio_id` | string UUID | Obligatorio; único por envío lógico; conservar en reintentos |
| `origen` | string | `web` para navegador/Flutter web, `app` para Flutter nativo; default del servidor `app` |

No enviar identidad, empresa, legajo, sucursal, fecha, hora, regla o cumplimiento horario: el servidor los obtiene automáticamente. No enviar fotos en base64 ni URLs en el JSON.

## Alta multipart con fotos

Mismos campos, como texto. `valida` acepta `"true"`/`"false"` o `"1"`/`"0"`. Cada archivo debe usar exactamente el nombre **`fotos`**, repetido: no `foto`, `fotos[]` ni un objeto JSON.

Hasta 5 fotos opcionales, cada una de hasta 5.242.880 bytes, JPG/PNG/WEBP y hasta 20 megapíxeles. El envío completo tiene límite de 28.311.552 bytes (27 MiB). Los formatos se verifican por su contenido. El servidor convierte a JPEG sin EXIF y guarda registro/fotos en una sola transacción. Si falla una foto, no queda una validación parcial.

En navegador, dejar que `FormData` construya `Content-Type` y su boundary. En Flutter web leer bytes; no usar rutas de archivos nativos. Conservar las mismas fotos y su orden al reintentar.

### Ejemplo JavaScript para web

`apiBase` incluye `/api/v1/mobile`. `envioId` se crea una sola vez al preparar el envío, por ejemplo con `crypto.randomUUID()`, y se conserva mientras se reintenta. `token` es el JWT de la sesión del empleado.

```javascript
async function registrarCarga({ apiBase, token, envioId, camionId, tipo, consolidado, valida, observaciones, fotos }) {
  const body = new FormData();
  body.append('camion_id', String(camionId));
  body.append('tipo', tipo);
  body.append('consolidado', consolidado);
  body.append('valida', String(valida));
  body.append('observaciones', observaciones ?? '');
  body.append('envio_id', envioId);
  body.append('origen', 'web');
  for (const foto of fotos) body.append('fotos', foto, foto.name);

  const response = await fetch(`${apiBase}/cargas`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body
  });
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error || 'No se pudo registrar'), { status: response.status });
  return result; // { registro, repetido }; éxito tanto con 201 como con 200.
}
```

Integrar con el mecanismo de renovación del token de la aplicación; ante 401, renovar y reintentar una vez con el mismo UUID y payload. Si vuelve a fallar, pedir inicio de sesión. El ejemplo se centra en el formato del envío.

### Ejemplo Flutter con el cliente existente

Archivo: `frontend_flutter/lib/src/core/network/mobile_api_client.dart`. Ya existen `getCargas`, `createCarga` y `getCargaFoto`; reutilizarlos para conservar renovación JWT y manejo de errores.

```dart
// apiClient: MobileApiClient; token: String; fotosBytes: List<Uint8List>.
// envioId: UUID creado una sola vez y guardado en el estado del formulario.
final config = await apiClient.getCargas(token: token, path: '/config');
final puedeCrear = config['habilitado'] == true;
final puedeVerHistorial = config['tiene_historial'] == true;

final result = await apiClient.createCarga(
  token: token,
  fields: {
    'camion_id': camionId.toString(),
    'tipo': tipo,
    'consolidado': consolidado,
    'valida': valida.toString(),
    'observaciones': observaciones,
    'envio_id': envioId,
    'origen': kIsWeb ? 'web' : 'app',
  },
  fotos: fotosBytes,
);
final registro = Map<String, dynamic>.from(result['registro'] as Map);
final validaCarga = registro['valida'] == 1;
final enHorario = registro['en_horario'] == 1;
```

`kIsWeb` proviene de `package:flutter/foundation.dart`. No enviar si el formulario no está habilitado o no pasó la validación. La pantalla implementada de referencia es `lib/src/presentation/attendance/cargas_page.dart`.

## Respuesta de alta y detalle

201 al crear; 200 al repetir el mismo envío. Ambos devuelven el mismo formato:

```json
{
  "registro": {
    "id": 101,
    "empresa_id": 1,
    "empleado_id": 10,
    "legajo": "0010",
    "empleado_nombre": "Pérez Ana",
    "sucursal_empleado_id": 1,
    "sucursal_empleado_nombre": "Central",
    "puesto_nombre": "Chofer",
    "camion_id": 7,
    "camion_numero": "014",
    "camion_patente": "AA123BB",
    "sucursal_camion_id": 2,
    "sucursal_camion_nombre": "Depósito",
    "fecha": "2026-09-29",
    "registrado_at": "2026-09-29T07:58:21-03:00",
    "tipo": "inicial",
    "consolidado": "000123",
    "valida": 1,
    "observaciones": "",
    "en_horario": 1,
    "horario_id": 1,
    "horario_nombre": "Carga inicial",
    "desde_minuto": 0,
    "hasta_minuto": 485,
    "origen": "web",
    "inicial_fecha": "2026-09-29",
    "fotos": [{"id": 501}]
  },
  "repetido": false
}
```

En una repetición `repetido` es true. `GET /cargas/101` devuelve directamente el objeto `registro`, sin wrapper ni `repetido`. `fotos` puede estar vacío. `inicial_fecha` es una propiedad calculada de solo lectura: fecha para inicial, null para recarga; usar `fecha` y `tipo` en la interfaz. El cliente debe tolerar propiedades adicionales. No se devuelven `envio_id` ni `envio_hash`.

Las sucursales del empleado y del vehículo son independientes. Los nombres, legajo, puesto principal y horario son los valores históricos al registrar; no reemplazarlos con los datos actuales del catálogo.

**Tipos:** `habilitado`, `tiene_historial` y `repetido` son booleanos JSON. `valida`, `en_horario` y `tiene_inicial` son enteros `0/1` en respuestas. Fechas `YYYY-MM-DD`; timestamps ISO 8601 con `-03:00`, potencialmente con fracciones de segundo. Mostrar horario argentino aunque el dispositivo use otra zona.

No confundir `valida=0` con ausencia de presentación, ni `en_horario=1` con una respuesta afirmativa. Un envío fuera de horario devuelve 201 igualmente, con `en_horario=0`.

## Historial y fotos

`GET /cargas?page=1` devuelve `{"items":[...],"total":42,"page":1,"per_page":30}`. Los items tienen los campos históricos del registro y `fotos_cantidad`, pero no el array `fotos`. Obtener el detalle para abrir la galería. Orden descendente por fecha/hora e ID. Siguiente página cuando `page * per_page < total`. Una página sin resultados tiene `items: []`.

Solo se admite paginación por `page` en la API móvil. Los filtros de empresa, sucursal, camión, fecha, búsqueda y `per_page` del panel no están disponibles en este endpoint. El historial devuelve solo registros del empleado autenticado dentro de su empresa actual. Otro empleado, aunque sea ayudante del mismo camión, no puede abrir estos detalles ni sus fotos (404).

Las fotos se descargan con Bearer desde `/cargas/fotos/{foto.id}`; respuesta `image/jpeg`, `Cache-Control: private, no-store`. No colocar el JWT en la URL ni suponer que `<img src="...">` enviará el header.

```javascript
async function obtenerFotoUrl(apiBase, token, fotoId) {
  const response = await fetch(`${apiBase}/cargas/fotos/${fotoId}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) throw new Error('No se pudo cargar la foto');
  return URL.createObjectURL(await response.blob());
}
// Usar la URL en <img> y llamar URL.revokeObjectURL(url) al cerrar o reemplazarla.
```

Flutter: `final bytes = await apiClient.getCargaFoto(token: token, id: fotoId);` y `Image.memory(bytes)`. Esto también sirve en Flutter web. No guardar fotos privadas en cachés compartidas.

## Duplicados, recargas y errores

- Una inicial por camión y día argentino. Una respuesta por camión, día y consolidado. Alcanza con un chofer o ayudante, no ambos.
- Para registrar una recarga tiene que existir una inicial de ese camión el mismo día, aunque la inicial haya sido tardía o su respuesta sea No. Cada recarga utiliza otro consolidado. No hay límite diario de recargas.
- La recarga no corrige el cumplimiento de la inicial. Se evalúa su propia ventana horaria.
- Deshabilitar el botón mientras se envía. Mantener `envio_id`, campos y bytes de fotos tras un timeout/error de conexión; un error de red no permite concluir si el servidor guardó o no.
- La clave está vinculada al empleado y su empresa. El servidor compara camión, consolidado normalizado, tipo, respuesta, observaciones y contenido/orden de las fotos. No cambiar esos datos y reutilizar el UUID: devuelve 409. Para un nuevo envío lógico, generar otro UUID.
- No generar automáticamente otro UUID ante un conflicto ni reenviar sin intervención los datos modificados. Revisar historial/configuración y mostrar el mensaje del servidor.
- No hay soporte offline: no declarar éxito ni usar la hora del dispositivo como hora de validación. Mostrar comprobante solo después de 200/201.

Errores de dominio: `{"error":"mensaje legible"}`. No existe un `code` estable para distinguir los distintos conflictos de cargas; no programar decisiones automáticas analizando textos traducibles.

| HTTP | Situación | Acción del cliente |
|---|---|---|
| 400 | Campos, UUID, observaciones o fotos inválidos | Mostrar mensaje y permitir corregir |
| 401 | JWT ausente/expirado o empleado inactivo | Recuperar sesión; reintentar una vez si se renueva |
| 403 | Puesto no habilitado para crear | Actualizar config; conservar acceso al historial si existe |
| 404 | Camión/recurso no encontrado o ajeno | Actualizar catálogo o cerrar detalle |
| 409 | Inicial/consolidado duplicado, UUID con otros datos, falta inicial, camión inactivo, falta legajo/sucursal o regla horaria | Mostrar mensaje y actualizar configuración/historial |
| 413 | Request demasiado grande | Reducir cantidad/peso de fotos; el proxy también puede devolver 413 sin JSON |
| 5xx / red | No se conoce si terminó el envío | Conservar payload/UUID y ofrecer reintento |

## Panel administrativo web

El panel existente usa rutas HTML con sesión de usuario administrativo, no Bearer de empleado. Todas las escrituras necesitan `csrf_token`. Los formularios exitosos redirigen a catálogos; no consumirlos como si devolvieran JSON.

| Método | Ruta desde el dominio (sin `/api/v1/mobile`) | Permiso `validacion_carga` |
|---|---|---|
| GET | `/validacion-carga/` | `ver` |
| GET | `/validacion-carga/{id}` | `ver` |
| GET | `/validacion-carga/fotos/{id}` | `ver` |
| GET | `/validacion-carga/exportar` | `exportar` |
| GET | `/validacion-carga/catalogos` | `ver` |
| GET, POST | `/validacion-carga/catalogos/{camiones\|horarios}/nuevo` | `ver` y `crear` |
| GET, POST | `/validacion-carga/catalogos/{camiones\|horarios}/{id}/editar` | `ver` y `editar` |
| POST | `/validacion-carga/puestos` | `editar` |
| GET | `/validacion-carga/auditoria` | `ver` |

Listado/exportación aceptan `desde`, `hasta` (fechas inclusivas), `q` (legajo/nombre/consolidado), `camion_id`, `sucursal_empleado_id`, `tipo`, `valida` y `en_horario` (estos dos últimos `0`/`1`). Listado: `page`, 30 registros; auditoría: `page`, 50. Solo admin puede seleccionar `empresa_id`; para otros usuarios el backend impone su empresa.

Camiones: `sucursal_id`, `numero` (40), `patente` (20), `descripcion` opcional (200), `activo=1` para activo. Horarios: `sucursal_id` opcional (general de empresa), `nombre` (100), `tipo`, `desde`/`hasta` en `HH:MM` (hasta admite `24:00`), `vigente_desde`, `vigente_hasta` opcional, `activo=1`. Puestos: `puesto_ids` repetido. Sin `activo=1`, el catálogo queda inactivo; no hay eliminación física.

Un frontend web separado para **empleados** consume la API Bearer anterior. Si se desea reemplazar el **panel administrativo** por una SPA, se necesita diseñar una API administrativa JSON adicional: no está implementada por estos endpoints.
