# Etapa 2A: resolución de configuración facial

Fecha: 20/10/2026.

## Implementado

`services/facial_policy_service.py` resuelve borradores con prioridad por
campo empleado → sucursal → empresa → predeterminado. Un campo ausente
o null hereda; disabled es una decisión explícita. Devuelve origen por
campo, configuración solicitada y modo efectivo por separado.

La activación está bloqueada en código. Ni el llamador ni un campo
configurable pueden declarar validado un proveedor. Los modos trial,
required y risk pueden describirse como borradores, pero no activarse.
El modo efectivo siempre es disabled y capture_enabled siempre false.

Límites iniciales de configuración: 1–5 intentos, 10–120 segundos.
No son umbrales biométricos ni valores validados en un piloto.

Se validan identidades del alcance y tipos estrictos. El llamador futuro
debe obtener los IDs de registros autorizados del servidor y comprobar
permisos administrativos; este módulo no sustituye autenticación/RBAC.

## Reutilización e integración pendiente

Se mantiene la arquitectura de servicios Python existente. No se agregan
dependencias, conexiones, endpoints ni un flujo alternativo de asistencia.

El resolvedor completo todavía no está conectado al contrato móvil.
La API no publica este objeto y Flutter todavía no lo interpreta.
La ampliación 2B siguiente permite preparar el modo por empresa.

Próxima unidad de trabajo: persistencia aditiva para configuración existente,
integración administrativa con permisos/auditoría y contrato móvil. Antes de
guardar políticas, definir semántica de revisión/versionado y guardar la
modificación junto con su auditoría. No reutilizar rostro_hash.

## Verificación

Comando ejecutado:

```text
python -m pytest tests/test_facial_policy_service.py -q -p no:cacheprovider
```

Resultado: 28 passed. Pruebas puras, sin base de datos ni red.
Cubren defaults, herencia por campo, desactivación explícita, bloqueo
de activación, alcance incorrecto, entradas inválidas, ausencia de sucursal
y ausencia de estado compartido entre resoluciones.

No se ejecutaron tests de regresión completos: no se modificaron sus
rutas ni dependencias. Estas pruebas no validan captura, PAD o identidad.

## Activación, recuperación y estado

No existe habilitación disponible en esta entrega. QR/GPS no llama al
nuevo servicio y mantiene su comportamiento.

Sin cambios de esquema o datos; no hay migraciones que revertir.
Para retirar esta unidad, revertir únicamente los nuevos archivos de
servicio, tests y documentación. No tocar fichadas ni cambios preexistentes.

Faltan las etapas de persistencia/panel/API/Flutter, selección y validación
del proveedor, enrolamiento, autorización, pruebas reales y piloto.
No presentar la etapa 2 completa ni el reconocimiento como implementado.

## Ampliación 2B: borrador por empresa

Se amplió el formulario existente de configuración con una sección separada
de preparación facial, sin otra pantalla ni endpoint. Su POST usa una acción
específica y no llama al guardado de reglas QR/GPS.

El usuario debe ser administrador activo y pertenecer a esa empresa o tener
alcance global (empresa_id null). La sección no se muestra a otros alcances.
Se conserva la protección CSRF del formulario existente.

`save_facial_draft` valida el modo y guarda borrador/revisión junto con un
evento en auditoria, en la misma transacción. La revisión detecta ediciones
concurrentes; cualquier error revierte ambas operaciones.

Migración preparada: `migrations/20261020_01_facial_company_draft.sql`.
Añade JSON nullable y contador de revisión a configuracion_empresa.
**No ejecutada ni conectada al bootstrap**. Hasta que se aplique mediante el
procedimiento de despliegue y exista la fila de configuración, la sección
informa que no puede guardar. No se activó ninguna política.

Archivos ampliados: repositorio de configuración, ruta editar y formulario
configuracion_empresa/form.html. Tests nuevos de guardado y autorización;
fixture existente actualizada para simular la nueva lectura del administrador.

Verificación final:

```text
python -m pytest tests/test_facial_policy_service.py tests/test_facial_company_draft.py tests/test_web_configuracion_empresa.py tests/test_web_permission_decorators.py tests/test_web_permissions_service.py -q -p no:cacheprovider --tb=short
44 passed
```

La primera ejecución de regresión encontró tres fallos por la nueva
dependencia de lectura del administrador no simulada en los tests existentes.
Se actualizó su fixture y la ejecución final pasó completa.
Sintaxis Jinja validada; no se realizó comprobación visual en navegador.
Tests de repositorio con conexiones simuladas: no validan ejecución real del
DDL ni una transacción MySQL real.

Pendiente: excepciones de sucursal/empleado, formulario completo de parámetros,
contrato móvil y pruebas de integración con una base de pruebas migrada.
Rollback operativo: revertir la sección y su ruta de guardado, manteniendo
las columnas aditivas y la auditoría. No borrar datos para desactivar.

## Ampliación 2C: excepciones por sucursal y empleado

Se reutilizó save_facial_draft con una lista cerrada de tablas/alcances.
Las actualizaciones de excepciones incluyen id, empresa_id y revisión en
el WHERE. El guardado y su auditoría permanecen en una misma transacción.

Se incorporó un parcial compartido `templates/partials/facial_draft.html`
a los formularios existentes de empleados y sucursales. El adaptador
`web/facial_draft_forms.py` controla el guardado separado y los permisos:
administrador activo de la empresa o global. RRHH no puede modificar estos
borradores aunque pueda editar otros datos del empleado.

Heredar guarda un objeto vacío; desactivado guarda un modo explícito.
Una falla de guardado muestra el error sin continuar con la actualización
general del empleado o sucursal. En esquemas sin las nuevas columnas no
aparece la sección; los formularios existentes siguen funcionando.

Migración aditiva preparada, NO ejecutada:
`migrations/20261020_02_facial_scope_drafts.sql`. Añade JSON nullable y
revisión en sucursales y empleados. MySQL no revierte ambos ALTER como
una transacción; inspeccionar columnas si una aplicación manual se interrumpe.

Validación:

```text
python -m pytest tests/test_facial_policy_service.py tests/test_facial_company_draft.py tests/test_facial_scope_forms.py tests/test_web_configuracion_empresa.py tests/test_web_empleados.py tests/test_web_permission_decorators.py tests/test_sucursal_geo.py -q -p no:cacheprovider --tb=short
68 passed, 2 skipped
```

Sintaxis de los tres templates validada con Jinja. Sin validación visual
en navegador ni aplicación de DDL. Las pruebas omitidas no se consideran
aprobadas. No se modificaron rutas de asistencia.

Pendientes de esta etapa: vista de la política heredada completa, parámetros
adicionales, contratos API/Flutter y pruebas con base de pruebas migrada.
La captura y la autorización facial continúan bloqueadas.
