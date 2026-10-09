# Viáticos y reintegros mensuales — contrato 1.35.0

Fecha: 08/10/2026. Backend compartido por frontend web de empleados y Flutter. La implementación del frontend móvil sigue siendo una tarea de integración. Este contrato reemplaza la descripción de carga independiente de 1.34.x para nuevas rendiciones; conserva aprobación, devolución, rechazo y pago.

## Reglas de negocio

- Un registro por empresa, empleado y mes calendario, identificado por `periodo: "AAAA-MM"`. No crear un registro por comprobante. La restricción existe también en la base de datos y cubre envíos simultáneos con UUID distintos.
- El empleado debe estar activo y pertenecer a un sector habilitado de su empresa. La empresa y el empleado se toman del token, nunca de campos enviados. Un cambio a un sector no habilitado conserva la lectura del historial, pero impide crear, editar o cancelar desde la API del empleado.
- Se puede crear y editar el mes actual o el anterior hasta el día 15 siguiente inclusive, según Argentina. Desde el 16 se bloquea crear, editar y enviar el período vencido. Administración puede cargar períodos vencidos dentro de su alcance.
- Un borrador admite gastos incompletos. Enviar valida cada gasto y pasa a `pendiente`; el empleado ya no puede editar hasta que se devuelva. Se mantiene la cancelación propia de borrador/devuelta/pendiente, sujeta a la ventana de carga.
- Estados existentes: `borrador`, `pendiente`, `devuelta`, `aprobada`, `rechazada`, `pagada`, `cancelada`. Enviado equivale a pendiente de aprobación, no es un nuevo estado.
- Una aprobación del jefe directo actual o RR. HH./admin basta. Se permite aprobación parcial por gasto. No se permite autoaprobación ni registrar el propio pago.
- Kilómetros opcionales: entero entre 0 y 1.000.000; `null` significa no informado/no corresponde, distinto de cero. Son informativos, no se multiplican por tarifa ni suman dinero. Foto del odómetro opcional.
- De 0 a 50 gastos: se permite enviar solo kilómetros, o declarar cero gastos y cero kilómetros. Combustible y peajes se cargan como gastos separados mediante los conceptos configurados por Administración.
- Se admiten importes iguales en varios gastos. Número de comprobante y emisor se guardan por gasto. Si coincide emisor y número con otro gasto activo no cancelado de la empresa, se devuelve una advertencia; no se bloquea por importe ni se revelan los datos del otro empleado.
- Cancelar no borra el registro ni libera el mes para crear otro. Los estados finales conservan su historial. Las solicitudes históricas sin período permanecen sin mes asignado y no se fusionan automáticamente.

## Configuración y acceso

Base: `/api/v1/mobile/reintegros`. Todas las rutas requieren `Authorization: Bearer <JWT mobile>`. Respuestas y fotos usan `Cache-Control: private, no-store`.

`GET /config` devuelve `version_contrato: "1.35.0"`, moneda ARS, estados, `conceptos` (y alias compatible `categorias`), límites, formatos de fotos, `recordatorios` no leídos y:

```json
{
  "mensual": {
    "habilitado": true,
    "fecha_actual": "2026-10-08",
    "periodos_habilitados": ["2026-09", "2026-10"],
    "reaperturas": [],
    "fecha_cierre_dia": 15,
    "kilometros_informativos": true,
    "foto_odometro_obligatoria": false
  }
}
```

`reaperturas` contiene `id` de solicitud, `periodo` y `reabierto_hasta`. No habilita a crear otro registro: abrir ese ID. Si `habilitado=false`, ofrecer historial sin carga. La API vuelve a verificar permisos, sector, estado y plazo al guardar, aunque la pantalla haya quedado abierta.

## Rutas

### Catálogo de conceptos: integración del selector

El CRUD se administra en **Viáticos → Conceptos de viáticos**, ruta web `/reintegros/categorias`, con sesión administrativa y CSRF. Requiere rol admin/RR. HH. y permiso `reintegros.editar`. No es una ruta Bearer para Flutter. El rediseño del panel no cambia los campos ni las rutas de la API; se conserva la versión 1.35.0.

- Al abrir o volver a la carga, consultar `GET /config` y construir el selector con `conceptos`: objetos `id`, `nombre`, `activo: 1`, ordenados por nombre. `categorias` es un alias compatible del mismo catálogo, no otro listado para combinar.
- Mostrar **Concepto** para el selector y **Descripción del gasto** para el texto libre. Enviar el ID elegido como `categoria_id` y la descripción como `concepto`. Nunca enviar el nombre como ID ni crear conceptos desde la app del empleado.
- Un catálogo vacío debe mostrar “No hay conceptos disponibles. Contactá a Administración”. Se pueden guardar borradores incompletos; no enviar gastos sin un concepto activo. La carga de kilómetros sin gastos mantiene sus reglas habituales.
- Si un concepto se desactiva con el formulario abierto, el backend rechaza su uso al guardar. Conservar los datos locales, actualizar config y pedir otra selección; no reemplazarla automáticamente por el primer concepto. También se valida un ID provisto al guardar borrador.
- En detalle e historial mostrar `gastos[].categoria_nombre`, guardado con el gasto, aunque el concepto se haya renombrado o desactivado. Al editar y guardar se valida el catálogo vigente y se toma su nombre actual para la nueva versión.
- Búsqueda local por nombre y selección única por gasto. Un mismo concepto puede usarse en varios comprobantes, incluso del mismo importe.
- Desactivar conserva los gastos e historial; no existe eliminación del catálogo en la API mobile.

Ejemplo del fragmento de config (IDs ilustrativos):

```json
{"conceptos":[{"id":1,"nombre":"Combustible","activo":1},{"id":2,"nombre":"Peajes","activo":1}]}
```

Para la interfaz mobile, mantener el botón principal de guardar/enviar claramente separado de cancelar o volver; usar áreas táctiles de al menos 44 px y mostrar progreso durante el envío. El rediseño del panel administrativo no implementa por sí mismo estas pantallas en Flutter.

| Método | Ruta relativa | Uso |
|---|---|---|
| GET | `/config` | Acceso mensual, conceptos, límites y avisos |
| GET | `/solicitudes` | Historial propio y totales |
| POST | `/solicitudes` | Crear el período, guardar borrador o enviar |
| GET | `/solicitudes/{id}` | Detalle propio, fotos, decisiones y pago |
| PUT | `/solicitudes/{id}` | Reemplazo completo de gastos de borrador/devuelta |
| POST | `/solicitudes/{id}/acciones` | Cancelación propia con revisión vigente |
| GET | `/fotos/{id}` | Comprobante privado de gasto |
| GET | `/odometro/{id}` | Foto privada del odómetro |
| GET | `/recordatorios` | Avisos no leídos, `items`, hasta 30 |
| POST | `/recordatorios/{id}/leido` | Marcar aviso propio como leído, devuelve `ok: true` |

Listado: filtros `periodo=AAAA-MM`, `estado`, `desde`, `hasta`, `page`; 30 filas por página. Desde/hasta corresponden a fecha de creación, ambos inclusive. Devuelve `items`, `page`, `per_page`, `total`, `total_solicitado` y `total_aprobado`. Totales de todas las páginas del filtro; aprobado incluye pagados. Importes string decimal con dos decimales. Cada fila incorpora `periodo` (null en histórico) y `kilometros`.

## Alta y edición

### Ejemplo mínimo: guardar un borrador mensual

`POST /api/v1/mobile/reintegros/solicitudes`, con Bearer y `Content-Type: application/json`:

```json
{
  "envio_id": "0245b8ce-1ea5-4b76-a4e5-cd31a5e19d20",
  "periodo": "2026-09",
  "accion": "borrador",
  "kilometros": null,
  "gastos": []
}
```

Guardar `solicitud.id` y `solicitud.revision` de la respuesta. Las siguientes cargas de ese mes se hacen con PUT al mismo ID; no crear una solicitud nueva por cada gasto. Antes de un alta, consultar `/solicitudes?periodo=2026-09` para recuperar una rendición iniciada desde otro dispositivo o por Administración.

### Ejemplo con varios comprobantes

Ejemplo de cuerpo, con IDs de concepto ilustrativos que deben obtenerse desde config:

```json
{
  "envio_id": "0245b8ce-1ea5-4b76-a4e5-cd31a5e19d20",
  "periodo": "2026-09",
  "kilometros": 850,
  "accion": "enviar",
  "observaciones": "Recorridos de septiembre",
  "gastos": [
    {"fecha":"2026-09-12","categoria_id":1,"concepto":"Peaje de ida","importe":"5000.00","numero_comprobante":"0001-123","emisor":"Concesionaria"},
    {"fecha":"2026-09-12","categoria_id":1,"concepto":"Peaje de regreso","importe":"5000.00","numero_comprobante":"0001-124","emisor":"Concesionaria"}
  ]
}
```

Con fotos nuevas, usar multipart: `gastos` es un único string JSON, archivos repetidos en `fotos_0`, `fotos_1`, … `fotos_49` según posición del array. Foto del odómetro bajo `odometro`, un único archivo opcional. El ejemplo suma ARS 10.000; los 850 km no modifican ese total.

Campos de gasto al **enviar**:

- `fecha`: requerida, del mes elegido, no futura.
- `categoria_id`: concepto activo de la empresa, obligatorio para rendiciones mensuales. Se mantiene este nombre de campo para compatibilidad. Administración crea/edita/desactiva conceptos; su nombre queda guardado en cada versión del gasto.
- `concepto`: descripción libre del gasto, obligatoria, máximo 500 caracteres; no confundir con el catálogo.
- `importe`: string decimal positivo, máximo `999999999.99`, hasta 2 decimales, sin coma ni separadores de miles. No enviar floats ni notación científica.
- `numero_comprobante`: texto opcional, máximo 100; conservar ceros a la izquierda y guiones. `emisor`: opcional, máximo 180. Informarlos cuando estén disponibles para detectar posibles duplicados.
- Fotos: entre 1 y 3 por gasto contando las conservadas. JPEG/PNG/WEBP, máximo 5 MiB y 20 megapíxeles por archivo. Backend normaliza a JPEG, 1800 px y hasta 2 MiB por imagen. Límite del envío 27 MiB y 20 MiB de nuevas imágenes de gastos procesadas/conservadas más el nuevo odómetro.

Borrador: `accion=borrador` permite `gastos: []` o gastos parciales con fecha/importe ausentes o null y descripción vacía. Si se provee un importe debe ser válido; la suma parcial cuenta solo los importes informados. Período, identidad y UUID siguen siendo obligatorios. Con JSON se puede guardar sin adjuntos. Observaciones generales: máximo 2000 caracteres.

En PUT enviar `revision` vigente, UUID válido, mismo `periodo` y **todos los gastos que deben permanecer**, no solo los modificados. No se puede cambiar el empleado o el mes. Agregar `fotos_existentes: [123,124]` dentro de cada gasto para conservar fotos activas del mismo registro; se pueden combinar con nuevos archivos hasta 3 por gasto. Omitir una foto existente la quita de la versión actual, conservándola internamente. No se pueden reutilizar fotos de otra solicitud ni de versiones antiguas. Esta función evita descargar y volver a subir imágenes desde Flutter.

El odómetro existente se conserva por defecto en PUT. Un archivo nuevo lo reemplaza. `quitar_odometro: "1"` lo quita; por defecto `"0"`. Las versiones anteriores se conservan internamente. `kilometros` debe reenviarse con el valor que se quiera conservar; omitirlo lo deja no informado. El envío consume la reapertura: una devolución posterior fuera del cierre requiere nuevo plazo explícito.

Alta: HTTP 201, `{"solicitud": <detalle>, "repetido": false}`. Mismo UUID/contenido: HTTP 200 con `repetido=true`. Conservar UUID durante reintentos; contenido diferente con la misma clave da 409. Otra clave para el mismo mes/empleado también da 409. Buscar el registro existente por `GET /solicitudes?periodo=AAAA-MM`; no generar otro UUID para resolver el conflicto.

PUT y acciones devuelven directamente el detalle. PUT no es idempotente: ante timeout consultar el estado/revisión antes de reintentar. Cancelar: `{"accion":"cancelar","revision":2}`. La API móvil no permite aprobar, pagar ni reabrir plazos.

### Ejemplo de PUT conservando un comprobante

`PUT /api/v1/mobile/reintegros/solicitudes/45`, con Bearer y JSON cuando no se adjuntan imágenes nuevas:

```json
{
  "envio_id": "0245b8ce-1ea5-4b76-a4e5-cd31a5e19d20",
  "revision": 2,
  "periodo": "2026-09",
  "accion": "enviar",
  "kilometros": 850,
  "gastos": [
    {
      "fecha": "2026-09-12",
      "categoria_id": 1,
      "concepto": "Peaje de ida",
      "importe": "5000.00",
      "numero_comprobante": "0001-123",
      "emisor": "Concesionaria",
      "fotos_existentes": [123]
    }
  ]
}
```

IDs y revisión ilustrativos: usar los del detalle vigente. Este PUT deja **únicamente el gasto incluido**; agregar al array todos los demás gastos que se quieran conservar. El ID 123 debe pertenecer a una foto activa de la solicitud 45. El odómetro existente se conserva al omitir el archivo y `quitar_odometro`.

### Comportamiento de los controles de la app

| Situación | Comportamiento esperado |
|---|---|
| `mensual.habilitado=false` | Mostrar historial y motivo; ocultar nueva carga y edición |
| Mes sin rendición, dentro de `periodos_habilitados` | Permitir crear borrador mensual |
| Rendición con `puede_editar_empleado=true` | Permitir guardar borrador o enviar con su revisión vigente |
| Pendiente/aprobada/rechazada/pagada/cancelada | Mostrar detalle; no ofrecer edición |
| Borrador/devuelta con plazo vencido | Mostrar cierre y pedir reapertura a Administración; no crear otro registro |
| Respuesta 409 | Consultar nuevamente el período/detalle y conservar cambios locales para revisión |
| `advertencias` no vacío | Mostrar posibles comprobantes repetidos sin tratar importes iguales como error |
| Recordatorios no leídos | Mostrar aviso y marcarlo mediante POST `/recordatorios/{id}/leido` |

La cancelación es una acción aparte: solo propia en borrador/devuelta/pendiente, con sector habilitado y plazo vigente; siempre respetar la validación del servidor. Los permisos de edición no son permisos de aprobación o pago.

## Detalle, errores e interfaz móvil

Detalle conserva identidad, moneda, totales, fechas, observaciones, motivo, empleado, gastos, historial y pago. Agrega `periodo`, `kilometros`, `foto_odometro_id`, `fecha_cierre`, `reabierto_hasta`, `puede_editar_empleado` y `advertencias: [{gasto_id,mensaje}]`. El período es AAAA-MM; fechas AAAA-MM-DD; timestamps con zona -03:00. Fecha/importe del gasto pueden ser null en un borrador incompleto.

`gastos` incluye `categoria_id`, `categoria_nombre`, `numero_comprobante`, `emisor`, `decision`, `motivo` y `fotos: [{id}]`. Descargar fotos y odómetro con Bearer; nunca incluir tokens en URLs. Los revisores administrativos tienen auditoría ampliada; el móvil solo recibe acción y fecha del historial. Nuevas acciones posibles: `crear_admin`, `editar_admin`, `reabrir`.

Errores JSON `{"error":"mensaje"}`: 400 validación; 401 sesión; 403 sector deshabilitado/plazo vencido/permisos; 404 ajeno o inexistente; 409 período duplicado/revisión o estado desactualizado; 413 tamaño; 503 migración pendiente. No mostrar éxito ante un error ni descartar el borrador local.

Pantallas recomendadas:

1. Acceso Viáticos y reintegros; consultar config y avisos.
2. Selección de mes entre los habilitados o apertura de una rendición ya existente. Mostrar el historial aunque el sector esté deshabilitado.
3. Kilómetros opcionales y odómetro opcional; lista de gastos, selector de concepto, descripción, número/emisor, importe y fotos. Total monetario separado de km.
4. Guardar borrador / Enviar. Antes de enviar, confirmar que quedará bloqueado para el empleado hasta una devolución.
5. Detalle con estado, decisiones por gasto, pagos, advertencias y plazo. Usar `puede_editar_empleado`, no inferir permisos solo por estado.
6. Avisos en la campana/listado mediante `/recordatorios`, con marcado de lectura autenticado.

## Recordatorio del día 5

El backend genera un aviso **dentro de la app**, no correo/SMS/push, para empleados activos de sectores habilitados que no tengan rendición del mes anterior o la tengan en borrador/devuelta. Una clave única por empresa/empleado/período evita duplicación entre procesos. Se comprueba cada hora y al iniciar el scheduler, solo el día 5 en Argentina. Requiere backend en ejecución ese día y que el frontend consulte/muestre los avisos; no hay recuperación retroactiva si el servicio estuvo caído todo el día 5.

<a id="crud-administrativo"></a>
## Panel administrativo

Acceso **Viáticos y reintegros**:

- **Sectores habilitados:** RR. HH./admin con permiso editar seleccionan sectores activos de su empresa. Sin sectores seleccionados, nuevas cargas deshabilitadas. No se habilitan automáticamente sectores reales durante la migración.
- **Administrar conceptos:** crear, editar y desactivar; no borrar conceptos referenciados. Crear al menos uno antes de enviar gastos.
- **Rendiciones mensuales:** una fila por empleado del alcance, incluyendo Sin cargar, Borrador y los estados existentes. Incluye empleados con una rendición aunque hayan cambiado de sector; personal sin registro se toma de los activos habilitados actuales. Exportación CSV de una fila por empleado, compatible con Excel, separando kilómetros, gastos y aprobado. No se genera XLSX en esta versión.
- **Nuevo reintegro:** permiso crear; empleado activo habilitado, con cero o varios gastos. Administración puede cargar meses vencidos. Borrador incompleto o enviar a aprobación.
- **Editar:** permiso editar; borrador, pendiente o devuelta. No modifica rendiciones aprobadas, pagadas, rechazadas o canceladas. Se conserva historial de versiones y usuario. Los borradores mensuales son visibles para la administración según su alcance.
- **Reabrir:** permiso editar, solo borrador/devuelta mensual; motivo obligatorio y fecha desde hoy hasta 31 días adelante. No habilita un sector deshabilitado. La reapertura no modifica importes, aprobaciones ni pagos.
- **Cancelar:** permiso eliminar, motivo obligatorio y estado borrador/pendiente/devuelta; baja lógica.
- **Revisar/pagar:** permisos y reglas anteriores conservados. Las rendiciones sin gastos pueden aprobarse con total cero. Un pago registrado nunca ejecuta una transferencia bancaria.

Usuarios de panel: RR. HH./admin ven su empresa; jefes ven reportes directos actuales y necesitan usuario vinculado al empleado. Permisos personalizados deben habilitar explícitamente `reintegros` (ver/crear/editar/eliminar/aprobar/exportar). Para Administración con alcance empresarial y registro de pago: `reintegros.ver` y `reintegros_pagos.editar`; agregar crear/editar solo si corresponde. Permiso de pago no concede aprobación general.

Rutas de panel: `/reintegros/`, `/reintegros/configuracion`, `/reintegros/categorias`, `/reintegros/mensual?periodo=AAAA-MM`, `/reintegros/mensual.csv?periodo=AAAA-MM`, `/reintegros/nuevo`, `/reintegros/solicitudes/{id}/editar`, `/reintegros/solicitudes/{id}/acciones`. Formularios con sesión y CSRF. La acción `reabrir` requiere revision, motivo y reabierto_hasta.

## Instalación y compatibilidad

Ejecutar en orden `scripts/migrate_20261007_02_reintegros.py` y `scripts/migrate_20261008_01_reintegros_mensuales.py`; reiniciar el proceso del backend. La segunda migración añade períodos, km, reaperturas, datos del comprobante, habilitación por sector, odómetro y avisos. Es repetible, no asigna meses a registros antiguos ni altera sus estados o importes. Las nuevas rendiciones exigen período; el frontend anterior debe actualizar su alta. Históricos conservan `periodo=null` y sus reglas originales de fecha de gasto, con el control actual de sector para escrituras del empleado.

Pruebas: `tests/test_reintegros.py` y `tests/test_reintegros_monthly.py`, ejecutadas sobre MariaDB aislado, nunca contra Railway.

Instalación del 08/10/2026: migración mensual aplicada a Railway y verificadas las cuatro tablas adicionales. Sectores inicialmente deshabilitados para que Administración seleccione cuáles corresponden; no se crearon rendiciones de prueba en la base real. OpenAPI validado.
