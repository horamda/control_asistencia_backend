# Habilitación de compensatorios

La habilitación es independiente del cálculo de vacaciones base y no acredita días automáticamente.

Antes de publicar esta versión, ejecutar `python scripts/migrate_20260930_01_compensatorios_habilitacion.py` en la base de destino. Es aditiva y repetible; crea dos tablas de configuración vacías. Nadie queda habilitado automáticamente, incluidos los nuevos empleados. No modifica movimientos ni saldos históricos.

En **Vacaciones → Quiénes reciben compensatorios**:

1. Seleccionar los puestos de chofer y cualquier otro puesto excluido; pulsar **Excluir puestos seleccionados**. Los puestos se identifican explícitamente, no por coincidencias de nombres.
2. Filtrar empleados por sector o puesto principal, seleccionar los visibles y desmarcar las excepciones. Pulsar **Habilitar seleccionados**. También se puede deshabilitar una selección.
3. Abrir **Cargar compensatorios** y acreditar días únicamente a los destinatarios elegidos entre los habilitados.

La exclusión por puesto prevalece sobre el permiso individual. Se comprueba el puesto principal y los adicionales activos cada vez que se intenta crear, editar o aprobar un compensatorio, incluida la carga masiva. Cambiar a un puesto excluido bloquea nuevas acreditaciones. Los permisos de una empresa anterior no se aplican al trasladar un empleado a otra empresa.

Deshabilitar a una persona no elimina acreditaciones anteriores; una corrección histórica se realiza revirtiendo el movimiento desde la gestión existente. La base, los compensatorios, los ajustes y el total siguen mostrándose por separado. Los filtros seleccionan personas actuales: no constituyen una regla automática para futuras incorporaciones.

La configuración requiere rol administrativo o RRHH, sesión web y CSRF, al igual que el módulo existente; sus cambios se registran en auditoría. La API de consulta conserva sus campos y los saldos históricos.

Pruebas: `python -m pytest tests/test_compensatorios_habilitacion.py tests/test_web_vacaciones.py tests/test_vacaciones_service.py tests/test_vacaciones_batch.py -q`.
