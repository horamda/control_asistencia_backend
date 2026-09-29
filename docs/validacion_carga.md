# Validación de carga

## Puesta en marcha

1. Ejecutar `python scripts/migrate_20260929_01_validacion_carga.py` contra la base de destino. La migración es aditiva y repetible. Crea horarios generales para las empresas existentes: inicial `[00:00,08:05)` y recarga `[11:00,24:00)`. No habilita puestos por similitud de nombres.
2. Abrir `/validacion-carga/catalogos`, elegir empresa y cargar camiones con sucursal, número interno y patente. Los identificadores son únicos por empresa.
3. Seleccionar exclusivamente los puestos de chofer y ayudante de reparto. Se comprueban el puesto principal y los adicionales activos. Sin esta configuración, nadie puede registrar.
4. Revisar horarios. Una regla de la sucursal del **camión** tiene prioridad sobre la general de empresa. No se admiten vigencias superpuestas para el mismo tipo y alcance. Las empresas creadas posteriormente deben configurar sus horarios desde este panel.
5. Asignar el módulo `validacion_carga` a los usuarios administrativos correspondientes. Por defecto solo admin tiene acceso; acciones: ver, crear, editar y exportar. Los no administradores quedan restringidos a la empresa de su usuario, incluso si alteran parámetros de la URL.
6. Publicar backend antes de la nueva versión Flutter. El home consulta `/cargas/config`; versiones anteriores del backend no muestran el acceso. Flutter y Flutter web usan el mismo formulario y autenticación existentes.

No hay una migración automática al iniciar Flask. El script de este módulo no ejecuta las otras migraciones del proyecto.

## Reglas

- Una carga inicial por camión y fecha argentina; una sola respuesta por consolidado/camión/fecha. Chofer y ayudante no tienen que responder ambos. Número de consolidado como texto, sin perder ceros iniciales, normalizado a mayúsculas.
- Recargas ilimitadas con distintos consolidados. Primero debe existir una carga inicial del mismo camión ese día; puede registrarse tarde y queda marcada fuera de horario. Una recarga no subsana el incumplimiento inicial.
- Inicio horario inclusive y fin exclusivo. A las 08:05 la inicial está fuera de horario; a las 11:00 la recarga está en horario con la configuración inicial.
- El backend registra la hora argentina de recepción/registro (UTC−03), nunca una fecha enviada por el cliente. Se guardan resultados Sí/No y cumplimiento horario por separado. Los envíos fuera de horario se conservan.
- Observación obligatoria para No; opcional para Sí. Máximo 2.000 caracteres.
- Guardado histórico de nombre, legajo, puesto principal, sucursal del empleado, datos y sucursal del camión y regla aplicada. Ediciones futuras no modifican validaciones anteriores.
- Los registros presentados no se editan ni eliminan. Catálogos se desactivan desde Editar. Cambios de configuración auditados en la misma transacción.
- Se permite elegir cualquier camión activo de la empresa del empleado, incluso de otra sucursal. Las sucursales del empleado y vehículo se guardan separadamente.
- Historial móvil privado del empleado. Empleados activos que dejan de tener un puesto habilitado conservan acceso a su historial, pero no pueden crear nuevas validaciones.
- Sin cola offline: los reintentos conservan `envio_id`; una respuesta perdida devuelve el mismo registro. El servidor rechaza reutilizar la misma clave con otro contenido.

## Fotos

Máximo 5 imágenes de 5 MB cada una, JPG/PNG/WEBP, hasta 20 megapíxeles. Se decodifican y convierten a JPEG (hasta 1.800 px por lado, sin EXIF) y se guardan en `carga_fotos` en la misma transacción que la validación. No se usan URLs públicas ni disco efímero. Un fallo de fotos revierte el registro completo. El acceso se autoriza por empresa en el panel y por empleado en la API, con `Cache-Control: private, no-store`.

Incluir estas tablas en el backup de MySQL y dimensionar su almacenamiento para el volumen de fotos. El límite total de request del módulo es 27 MB; el proxy de despliegue debe admitir ese tamaño. No hay borrado automático de evidencias.

## API

Prefijo `/api/v1/mobile/cargas`, JWT Bearer existente.

| Método | Ruta | Función |
|---|---|---|
| GET | `/config` | Habilitación, historial disponible, camiones y horarios vigentes |
| POST | raíz | Registrar JSON sin fotos o multipart con campos `fotos` repetidos |
| GET | raíz `?page=1` | Historial propio, 30 registros por página |
| GET | `/{id}` | Detalle propio con IDs de fotos |
| GET | `/fotos/{id}` | JPEG privado; JWT también requerido en esta solicitud |

Ejemplo JSON de alta:

```json
{"camion_id":1,"tipo":"inicial","consolidado":"000123","valida":true,"observaciones":"","envio_id":"08271a75-ff73-479e-9304-5e9f949330f7","origen":"web"}
```

`tipo`: `inicial` o `recarga`. Multipart acepta `valida` como `true`/`false` o `1`/`0`. No se aceptan omisiones del resultado. Identidad, empresa, sucursal y fecha se calculan en el servidor; no se toman del body. Respuesta nueva 201; repetición idéntica 200: `{"registro": {...}, "repetido": false}`. Fechas ISO 8601, fecha/hora con `-03:00`. Booleanos persistidos del registro (`valida`, `en_horario`, `tiene_inicial`) como 0/1; flags de configuración `habilitado` y `tiene_historial` como booleanos JSON.

Errores: 400 datos/fotos inválidos; 401 sesión; 403 puesto no habilitado; 404 recurso ajeno/inexistente; 409 duplicados, vehículo inactivo, falta inicial o configuración horaria; 413 request demasiado grande. Formato `{"error":"mensaje"}`.

## Consulta administrativa

Listado paginado y CSV con filtros de fechas, empleado/legajo/consolidado, camión, sucursal del empleado, tipo, respuesta y cumplimiento horario. Detalle con fotos e información histórica. Historial separado de modificaciones de camiones, horarios y puestos. El CSV neutraliza fórmulas de hojas de cálculo.

No se calculan cargas pendientes/no presentadas porque no existe un padrón de consolidados esperados. Tampoco se integran automáticamente los consolidados con otro sistema logístico.

## Validación técnica

`python -m pytest tests/test_carga_service.py tests/test_carga_integration.py -q`

Las pruebas de integración requieren un MySQL/MariaDB local aislado con `CARGA_TEST_DB_PORT`. Crean una base `carga_test_<uuid>`, aplican dos veces la migración, usan datos sintéticos y eliminan solo esa base. Nunca toman credenciales de `.env`. Cubren transacciones, concurrencia, privacidad, catálogos, horarios, snapshots, puestos adicionales y rutas. Sin esa variable, se omiten explícitamente.

En Flutter: `flutter test test/cargas_api_test.dart test/cargas_page_test.dart test/attendance_home_action_presenter_test.dart` y `flutter analyze` sobre los archivos modificados.
