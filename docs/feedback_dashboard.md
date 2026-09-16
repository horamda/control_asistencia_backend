# Resumen general de Feedback

## Comportamiento

- Periodo inicial: mes actual y once meses anteriores, hasta hoy.
- Atajos: este mes, seis meses y doce meses. Conservan sector, sucursal y estado del empleado.
- Rango personalizado de hasta tres anios; no admite fechas futuras ni rangos invertidos.
- El periodo siempre se refiere a la fecha de registro (`created_at`). Los estados
  y vencimientos corresponden al momento de consultar, no a un cierre historico.
- Se incluyen empleados activos e inactivos por defecto, para conservar la historia.
- Las barras incluyen meses sin registros, numeros visibles y enlaces accesibles
  por teclado. Los meses incompletos se identifican como parciales/en curso.
- Las tarjetas y barras abren el listado con las mismas fechas y filtros. La
  paginacion conserva esos filtros.

## Agrupacion de sucursales

Dolores y Chascomus se presentan como **Dolores** dentro de cada empresa. Se
normalizan mayusculas y acentos, y tambien se reconoce el nombre combinado
Dolores/Chascomus. No se modifican sucursales ni registros en la base.

El resumen y sus enlaces usan la agrupacion; en el listado se identifica con
`sucursal_grupo=1`. Las consultas operativas ordinarias pueden seguir seleccionando
una sucursal individual. La sucursal del caso es la guardada en el feedback,
con la sucursal actual del empleado como respaldo para registros anteriores.

## Consistencia y permisos

Todos los agregados usan el mismo filtro de fecha, sector, sucursal y estado
del empleado, incluidas las diez primeras personas del ranking. Los permisos
existentes de admin/RRHH y de sector permanecen vigentes. Sin empleado/sector
valido para un usuario restringido no se consultan casos.

El cumplimiento del plazo usa solo resueltos con fechas suficientes. Sin casos
evaluables muestra **Sin datos**. Los pendientes sin plazo y resueltos sin fechas
suficientes se informan aparte. Los totales globales de clientes y motivos ya no
se mezclan con los indicadores filtrados; se conservan accesos a sus catalogos.

## Implementacion y verificacion

- Cinco consultas agregadas en una conexion. Ranking limitado en SQL.
- Filtro directo por rango de `created_at`, con fin exclusivo al dia siguiente.
- Grafico HTML/CSS sin librerias externas ni solicitudes adicionales del navegador.
- 73 pruebas: rutas, servicio, consultas, permisos, fechas y agrupacion.
- Verificacion MySQL de solo lectura: resumen, suma mensual, suma por sucursal y
  cantidad del listado coinciden en tres escenarios (general, Dolores agrupado y
  seleccion inexistente).
- Revision visual en navegador pendiente: el navegador integrado no estaba disponible.

Requiere desplegar el backend y los estilos. No requiere migraciones de datos.
