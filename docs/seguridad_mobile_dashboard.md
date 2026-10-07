> Actualización 1.33.2: rankings y agrupación de accidentes por sucursal consultan la ficha actual de empleados de FichaYa. Nombres, legajos y organización no se toman del snapshot del reporte. El detalle individual mantiene los datos originales para auditoría. No cambia el JSON.

> Actualización 1.33.1: días sin accidentes toma el último accidente pendiente o aprobado del alcance (empresa, sucursal actual o propio), por fecha del evento hasta el corte. Excluye rechazados y anulados. No requiere inicio configurado cuando existe accidente. Sin accidente se usa el inicio confiable; si tampoco existe, se devuelve null. El récord requiere inicio configurado. Los totales, historial propio y rankings conservan el criterio de aprobados. `inicio` puede ser null aunque `disponible` sea true. `accidentes_registrados` cuenta todos los accidentes considerados hasta el corte. La sucursal de la API sigue siendo la del empleado autenticado.

# Seguridad e Higiene: contrato mobile 1.33.1

Base: `/api/v1/mobile/seguridad`. API compartida por frontend web de empleados,
Flutter web y Flutter nativo. Todas las rutas requieren `Authorization: Bearer <token>`
y un empleado activo. La identidad, empresa y sucursal se obtienen del token y del
empleado; los parámetros `empresa_id`, `empleado_id` y `sucursal_id` no seleccionan
otra identidad. No usar las rutas HTML del panel ni cookies/CSRF para esta API.

## Pantallas recomendadas

1. **Mi seguridad:** tarjetas de seguros, inseguros, accidentes e incidentes,
   mes/año seleccionables y acceso al historial de cada tipo.
2. **Mi historial:** lista paginada por tipo, fecha y estado; los registros propios
   solo aparecen una vez aprobados. **Mis envíos** conserva su flujo separado,
   con los estados pendiente, aprobado, rechazado y anulado.
3. **Indicadores:** días sin accidentes, récord y fecha del último accidente para
   empresa, sucursal actual y propio empleado. Los indicadores colectivos no incluyen
   nombres, fotos, descripciones ni IDs de accidentes de compañeros.
4. **Rankings:** seguros e inseguros por separado, por año y mes opcional, con alcance
   empresa o sucursal actual. Resaltar `mi_posicion`. No crear rankings de accidentes.
5. **Nuevo reporte:** conservar el alta con UUID, empleados/externos y fotos privadas.

Los rankings son conteos de observaciones, no una calificación integral de las personas.
No compensar comportamientos inseguros con seguros. El detalle de otro empleado
continúa prohibido aunque aparezca su nombre en el ranking.

## Configuración

`GET /config` conserva sus campos y agrega:

```json
{"dashboard":{"version_contrato":"1.33.1","historial_propio":true,"indicadores":true,
"ranking_alcances":["empresa","sucursal"],"sucursal_id":1}}
```

Sin sucursal, `ranking_alcances` contiene solo `empresa` y `sucursal_id` es `null`.
Usar esta capacidad para habilitar las nuevas pantallas; clientes anteriores siguen funcionando.

## Resumen personal

`GET /resumen?anio=2026&mes=9`

`anio` es opcional (año actual), entre 2000 y el año actual; `mes` es opcional,
1–12. Omitirlo consulta el año completo. No acepta seleccionar otro empleado.

Respuesta `200` (esquema completo: `SeguridadResumen` en OpenAPI):

- `anio`, `mes` (nullable), `fecha_corte` (`YYYY-MM-DD`), `estado: "aprobado"`.
- `total`: eventos aprobados del propio empleado en el período, sin duplicarlos
  aunque involucren a varias personas.
- `por_tipo`: objeto con `seguro`, `inseguro`, `accidente`, `incidente`, siempre presentes.
- `meses`: `[1,2,3,4,5,6,7,8,9,10,11,12]`.
- `series_mensuales`: los cuatro tipos, cada uno con un arreglo de 12 valores del
  año seleccionado; el filtro `mes` afecta las tarjetas, no recorta el gráfico anual.
- `comparativo_anual`: los cuatro tipos, cada uno con una lista de `{anio, valores}`.
  Cada serie tiene 12 posiciones enero–diciembre. Incluye desde el menor año entre el historial propio aprobado y el año seleccionado
  hasta el actual, con los años intermedios sin registros en cero; se ordenan de menor a mayor. Es independiente del
  filtro `anio/mes` de las tarjetas y llega hasta `fecha_corte`.
- `indicadores`: el mismo objeto de `/indicadores`, con corte a hoy, independiente
  del año/mes seleccionado para el historial.
- `actualizado_at`: fecha y hora ISO 8601 con zona `-03:00`.

En las series, `0` significa sin reportes aprobados cargados; `null` significa mes
futuro. El mes actual es parcial. No dibujar `null` como cero ni unirlo a una línea.
Ejemplo de una serie: `{ "anio": 2026, "valores": [0,1,0,0,2,0,0,1,0,0,null,null] }`.
Este ejemplo ilustra la forma; no representa datos reales.

## Indicadores sin detalles de compañeros

`GET /indicadores` o `GET /indicadores?hasta=2026-09-30`.
`hasta` es opcional (hoy), desde el año 2000 y no puede ser futura.

Respuesta: `hasta`, `sucursal_id` nullable, `criterio` y `alcances` con tres claves:
`empresa`, `sucursal`, `propio`. Cada alcance tiene:

| Campo | Tipo / significado |
|---|---|
| `disponible` | Booleano; si es falso, mostrar el motivo y no un cero |
| `motivo` | `null`, `sin_inicio_configurado`, `sin_sucursal`, `corte_anterior_al_inicio` |
| `inicio` | Fecha confiable de inicio, o `null` |
| `dias_sin_accidentes` | Entero no negativo, o `null` |
| `record_dias_sin_accidentes` | Entero no negativo, o `null` |
| `ultimo_accidente` | Fecha del último accidente pendiente o aprobado del alcance hasta el corte, o `null` |
| `accidentes_registrados` | Eventos únicos considerados hasta el corte, o `null` |

La fecha confiable se configura exclusivamente en el panel administrativo. No se infiere
del primer reporte ni de los años importados. El alcance propio usa la fecha mayor entre
ese inicio y la fecha de ingreso del empleado, cuando esta última está disponible.
Sin fecha de ingreso se usa la cobertura configurada del registro, no una antigüedad estimada.

Un accidente pendiente o aprobado reinicia la racha; un incidente no lo hace. Se usan días
calendario transcurridos. El récord excluye los días con accidentes. Al consultar una fecha
pasada se refleja el estado de aprobación actual de los reportes, no una reconstrucción
del estado que tenían en aquella fecha.

La sucursal es la actual del empleado autenticado; sus accidentes colectivos se identifican
por la sucursal actual de la ficha de empleados. Un evento con varios empleados
de esa sucursal cuenta una vez. Sin sucursal asignada se devuelve `sin_sucursal`;
nunca se sustituye silenciosamente por toda la empresa. Los externos no tienen sucursal
propia y no generan indicadores personales en mobile.

## Historial y detalle existentes

`GET /eventos?vista=propio&tipo=inseguro&desde=2026-01-01&hasta=2026-12-31&page=1`.
Filtros admitidos: `vista` (`propio`/`enviados`), `tipo`, `estado`, `desde`, `hasta`, `page`.
Los filtros de identidad/organización y búsqueda no se aplican en mobile.
Respuesta: `items`, `total`, `page`, `per_page=30`; finalizar paginado cuando
`page * per_page >= total`. Lista vacía es un estado válido.

`GET /eventos/{id}` y `GET /fotos/{id}` mantienen el control de acceso. Usar Bearer
también para fotos; en web, descargar como blob autenticado y revocar su URL al desmontar;
en Flutter nativo puede usarse un proveedor de imagen con headers. No construir enlaces públicos.
No se expone la identidad del denunciante ni la auditoría administrativa.

## Ranking

`GET /ranking?anio=2026&mes=9&alcance=sucursal`.

`alcance` nuevo: `empresa` (predeterminado compatible) o `sucursal` (solo la del empleado).
`anio` y `mes` mantienen su contrato anterior: año 2000–2100 y mes opcional 1–12.
La respuesta conserva `anio`, `mes`, `rankings`, `rankings_externos`, `eventos`, y agrega:

- `alcance` y `sucursal_id` (solo presente con valor en alcance sucursal; si no, `null`).
- `mi_posicion`: `{seguro: fila|null, inseguro: fila|null}`. Cada fila contiene
  `empleado_id`, `nombre`, `legajo`, `cantidad`, `posicion`.

Empates comparten posición (1,1,3). Sin observaciones propias: `null`, no posición cero.
`rankings` y `rankings_externos` solo contienen `seguro` e `inseguro`; no incluyen lesiones,
accidentes, incidentes, comentarios ni fotos. En alcance sucursal, externos queda vacío
porque esas personas no tienen sucursal asignada.

## Integración web / Flutter

Al abrir: cargar `/config` y `/resumen` sin bloquear uno por otro. `/resumen` ya incluye
indicadores: no repetir `/indicadores` salvo que se elija otro corte o solo se refresquen
las rachas. Cargar `/ranking` al entrar a esa pestaña, y el historial por demanda.
Al cambiar año/mes o alcance, descartar respuestas anteriores para no mostrar datos atrasados.
Invalidar el resumen después de una aprobación/edición detectada al refrescar; las altas
pendientes no se suman como aprobadas. No guardar datos entre sesiones de empleados distintos.

Web: `fetch(base + '/resumen?anio=2026', {headers: {Authorization: 'Bearer ' + token}})`.
Flutter: decodificar `valores` como `List<int?>`, fechas como fecha sin hora y posiciones
como objetos opcionales. Nunca hacer `null ?? 0` para indicadores no disponibles.

Errores: `400 {error}` para parámetros inválidos o ranking de sucursal sin asignación,
`401` para sesión inválida/inactivo, `404` para evento/foto inexistente o no autorizado.
Las respuestas usan `Cache-Control: private, no-store`.
No hay endpoint mobile para configurar cobertura, aprobar reportes ni editar indicadores.

## Publicación

Requiere la migración aditiva `20261005_02_seguridad_dashboard` (además de las migraciones
previas del módulo). Publicar backend antes de habilitar las pantallas en los clientes.
Este cambio implementa API y contrato; la presentación de las nuevas pantallas Flutter
debe consumir estas capacidades y contratos, sin alterar el alta existente.
