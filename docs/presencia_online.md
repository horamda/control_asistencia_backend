# Pantalla de presencia

La aplicación sirve una pantalla pública de solo lectura en `/presencia`.
Se puede compartir el enlace del servidor existente agregando `/presencia`.
No requiere cuenta. Devuelve cantidades y la lista mínima de empleados con
ingreso sin salida: nombres, sector, modalidad, hora de ingreso y validación
de ubicación. No publica legajos, DNI, teléfonos, fotos ni coordenadas.
El enlace no es una clave de acceso: cualquier visitante puede consultar estos
datos. Se solicita a los buscadores que no indexen la página.

La página consulta `/presencia/datos` cada 30 segundos, permite actualizar
manualmente y muestra el momento de la última consulta correcta. Ante errores
conserva los valores anteriores con un aviso de desactualización, sin convertir
una falla de conexión en cero presentes.

La pantalla prioriza la lista de personas por sucursal y sector, con búsqueda,
filtro de sucursal, impresión y diseño adaptable a celular. Distingue ingresos
por QR con GPS aceptado de ubicaciones a verificar. No confirma ocupación física
actual ni evacuación: se deben contrastar las fichadas con el recuento físico.
La sucursal es la asignada en el maestro. No se usa la modalidad para inferir
ubicación. Los turnos anteriores y los visitantes quedan fuera de la consulta.

## Cálculo

- Empleados activos: empleados activos de empresas activas.
- Vinieron hoy: personas distintas con al menos un ingreso hoy.
- Presentes ahora: personas cuya última marca de hoy es ingreso.
- Retirados: vinieron hoy y su última marca es egreso; pueden volver a ingresar.
- Sin ingreso: activos sin ingreso registrado hoy, no un cálculo de ausentismo.

Se utilizan las marcas detalladas en orden de hora e identificador, incluidas
las salidas y vueltas de pausas. Si el empleado no tiene marcas detalladas en
esa fecha, se usan los ingresos/egresos de `asistencias` como respaldo.
No se cuentan marcas posteriores a la hora de consulta. El día se determina
en hora de Argentina (UTC−3), independientemente de la zona horaria del servidor.
El corte es por día calendario: turnos comenzados ayer no se incluyen; una
salida sin fichar puede sobreestimar la presencia. No representa un control
físico independiente de las fichadas.

## Acceso

Para una sola empresa: `/presencia?empresa_id=1` (reemplazar por su ID real).
Sin ese parámetro se muestran los totales y el desglose de todas las empresas
activas. El filtro no limita el acceso a las otras empresas.

No requiere migraciones ni dependencias nuevas. Para verlo por Internet se
debe desplegar esta versión en el servidor web del proyecto, con su base de
datos habitual. Para verlo en la red local, el servidor debe ser accesible
desde los dispositivos de esa red. La implementación local no publica por sí
sola el sitio en Internet.

Verificación: `python -m pytest tests/test_presencia.py -q`.
