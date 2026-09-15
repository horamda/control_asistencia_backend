# Corrección administrativa de fechas de feedback

Acceso: **Sistema → Corrección FDBK**, ruta `/feedback/correccion-fechas`.
Solo usuarios activos con rol `admin`; los permisos generales de Feedback no
habilitan esta pantalla. Las mismas restricciones se aplican a GET y POST.

El listado incluye feedbacks de empleados activos e inactivos y permite buscar
por número, empleado, cliente o motivo, filtrar por estado, sucursal, número
exacto de cliente, empleado, motivo, sector de origen o responsable,
cumplimiento del plazo y rangos de carga y resolución. Los rangos incluyen
todo el día final y los filtros se conservan al paginar.
Cada registro tiene un formulario con sus fechas actuales y nuevas, y requiere
un motivo de corrección de hasta 160 caracteres.

Al modificar la carga se recalculan `fecha_limite` y `fecha_vencimiento` usando
el plazo **actual** del motivo (horas o días), incluso si el motivo está inactivo.
Si solo cambia la resolución se conserva el vencimiento. Se actualiza
`resuelto_en_sla`; los reportes también consultan las fechas corregidas.
La resolución es obligatoria solo para casos resueltos, no puede preceder la
carga y no se cambia el estado, responsable ni descripción de resolución.

Los cambios y la auditoría se confirman en una única transacción con bloqueo
del feedback. Un formulario desactualizado se rechaza. Si falla cualquier
escritura, se revierte toda la operación. Se mantiene la protección CSRF.

La auditoría usa `tabla_afectada = feedback_fechas` y el ID del feedback.
Una fila registra el motivo y otras registran cada campo anterior y nuevo;
cada fila identifica al usuario y la fecha del cambio. Este formato respeta
el límite de 255 caracteres de `auditoria.accion`. Estas entradas solo se
incluyen en la pantalla de auditoría para administradores y se excluyen de
la actividad reciente del inicio. No se generan notificaciones de feedback.

No requiere nuevas tablas ni migraciones con el esquema actual
(`auditoria.tabla_afectada` VARCHAR(100)). Publicar el backend actualizado para
habilitarlo en Railway; no depende de `presencia_web`.

Verificación local, sin modificar feedbacks reales:

```text
python -m pytest tests/test_feedback_dates.py tests/test_feedback_routes.py tests/test_feedback_service.py tests/test_web_permission_decorators.py -q
```
