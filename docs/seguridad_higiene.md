# Seguridad e Higiene — API 1.32.0

## Activación

1. Ejecutar `python scripts/migrate_20261002_01_seguridad_higiene.py` antes de publicar backend. Migración aditiva, repetible, con catálogos iniciales para empresas existentes. Repetir no borra ni reactiva categorías.
   Ejecutar también `python scripts/migrate_20261005_01_seguridad_externos.py` para registrar personas externas y su participación. No clasifica respuestas del histórico.
2. Asignar el módulo **Seguridad e Higiene** (`seguridad_higiene`) a usuarios elegidos. Admin lo incluye por defecto. Permisos independientes: `ver`, `crear`, `editar`, `aprobar`, `eliminar` (anular), `exportar`. Revisores necesitan `ver` + `aprobar`; no hay un rol fijo obligatorio.
3. Revisar catálogos en `/seguridad-higiene/catalogos`. Las empresas creadas posteriormente cargan sus catálogos desde el panel.
4. Publicar backend antes de Flutter. La app muestra **Seguridad e Higiene** junto a los demás accesos.
5. Subir el Excel en **Importar histórico**, resolver inconsistencias y crear eventos pendientes. Aprobarlos desde la bandeja.

Fotografías, Excel original y filas se almacenan en MySQL; incluir tablas `sh_*` en backups. El proxy debe admitir 27 MB por envío. Importador: XLSX hasta 10 MB, 50 MB descomprimidos, 5.000 respuestas.

## Reglas y privacidad

- Tipos separados: `seguro`, `inseguro`, `incidente` (sin lesión), `accidente`.
- El empleado reporta sobre sí mismo, compañeros activos de su sucursal o personas externas. Administración selecciona dentro de su empresa; importación admite empleados históricos inactivos.
- Entre 1 y 100 involucrados únicos sumando empleados y externos. Para empleados se conservan nombre, legajo, sucursal, sector y puesto. Para externos, nombre y empresa/procedencia; no se crea un legajo ficticio.
- Fecha del evento independiente de la recepción del servidor en Argentina. Fechas entre 2000 y hoy, nunca futuras.
- Seguro/inseguro requieren categoría activa del tipo y descripción. Inseguro requiere `advertido=si|no`. Accidente/incidente requieren lugar y hora. Administración completa los datos técnicos que correspondan.
- Todo nuevo evento queda `pendiente`, incluido el importado o creado por admin. Rechazar/anular requiere motivo; no hay borrado físico de eventos. Editar vuelve a pendiente y retira del ranking hasta nueva aprobación.
- Administración puede retirar fotografías incorrectas al editar; dejan de estar disponibles por API, pero se conservan en la base y se registra la operación en auditoría.
- `revision` impide decisiones sobre versiones desactualizadas. Escrituras de eventos y auditoría son transaccionales.
- El reportante consulta sus envíos y estados. El involucrado solo consulta eventos aprobados propios: sin identidad del reportante, notas administrativas, auditoría ni lista de otros involucrados.
- Rankings de la misma empresa con nombres y legajos, seguros/inseguros separados. Cantidad descendente; empates 1,1,3. Año/mes por fecha del evento, no de aprobación. Una observación por persona; estadísticas generales cuentan eventos distintos. Accidentes e incidentes no forman parte del ranking mobile.
- Acciones correctivas: descripción, responsable, vencimiento y estado pendiente/en curso/cerrada/anulada. Cierre/anulación requieren evidencia textual o motivo; se pueden adjuntar fotos al evento como evidencia.

## Importación

Detecta los encabezados reales `Marca temporal` y `Que va a notificar`, aun con títulos encima. Conserva el XLSX byte por byte y cada respuesta no vacía, incluidos datos sin cabecera, fórmulas como texto y enlaces a fotos. Cabeceras y filas vacías también permanecen en el archivo original.

Sugiere personas solo por coincidencia única normalizada de nombre/apellido dentro de la empresa; no vincula por similitud. Fechas inválidas, nombres ambiguos, campos faltantes y la categoría antigua Accidente-Incidente requieren resolución explícita. La revisión inicial se vuelve a calcular con los datos actuales al procesar o abrir cada fila.

El mismo archivo no crea otro lote (SHA-256). Una respuesta idéntica en otra exportación usa una clave determinista y puede vincularse al evento existente si la resolución coincide. Si difiere, exige revisión, sin sobrescribir. Las filas pendientes se conservan hasta resolverlas.

Los enlaces privados de Drive se preservan; no se descargan sin acceso. El administrador puede adjuntar fotos al resolver o editar. El nombre histórico de quien notificó se conserva en el original; no se atribuye al usuario que importa.

### Plantilla editable y corrección del histórico

En **Importar histórico**, `Descargar plantilla Excel` crea un XLSX con 100 filas disponibles, IDs estables, legajos (incluidos inactivos), categorías activas, listas desplegables y revisión mediante fórmulas. Cada lote ofrece `Descargar Excel para corregir`, con todas sus respuestas y una hoja Original de consulta. La descarga de un lote requiere `ver` + `crear` + `exportar`; la plantilla requiere `ver` + `crear`. Ambas descargas respetan la empresa del usuario y no se almacenan en caché.

- Hoja de entrada: **Carga**. No cambiar sus encabezados. Una fila por evento; múltiples legajos separados con `;`. Los legajos se comparan como texto exacto dentro de la empresa, conservando ceros iniciales. El nombre es solo una referencia.
- Fechas: fecha nativa de Excel o `AAAA-MM-DD`; horas `HH:MM` o hora nativa de Excel. Los mismos campos obligatorios del servicio se exigen al importar.
- La columna Revisión ayuda en Excel y se recalcula al editar. La validación definitiva es del servidor: también detecta legajos ambiguos, IDs reutilizados y cambios en los catálogos posteriores a la descarga.
- Una plantilla con errores se rechaza **antes de guardar el lote**, con hoja, fila y campos a corregir. No se aceptan fórmulas en los campos de entrada. Las hojas auxiliares no son respuestas.
- Se puede subir solo el subconjunto completo, retirando temporalmente de Carga las otras filas. Las respuestas incompletas siguen conservadas en el lote original.
- ID registro evita duplicados entre cargas. Fila origen vincula la corrección con su respuesta previa; ambos se verifican por empresa. Al crear o vincular el evento se resuelven las dos filas, sin modificar el original y en la misma transacción. Cambiar los datos de un ID ya importado requiere editar el evento en el panel.
- Preparar la plantilla no aprueba ni publica eventos. Después de subir, se procesan desde el lote y quedan pendientes de aprobación.
- El formato original de Google Forms sigue funcionando con conservación de filas incompletas. La revalidación carga empleados y catálogos una vez por lote; el servicio vuelve a comprobar los datos al crear cada evento.

Rutas administrativas: `GET /seguridad-higiene/importar/plantilla` y `GET /seguridad-higiene/importar/<id>/corregir`. La generación de plantillas no agrega endpoints mobile; el soporte de externos requiere la migración indicada arriba.

### Personas externas (API 1.32.0)

El reportante sigue siendo el empleado autenticado. `involucrados` contiene IDs de empleados; `externos` contiene personas externas. Se admite un evento solo con externos (`involucrados: []`) o mixto. Para un externo nuevo, **solo el nombre es obligatorio**, máximo 180 caracteres; `empresa` (empresa/procedencia) es opcional, máximo 180. Para reutilizar una persona, enviar su `id`; se verifica empresa y disponibilidad. No se unifican personas automáticamente por nombre, para evitar confundir homónimos.

```json
{
  "envio_id": "8562f710-bf2b-46d0-90bb-dd621278ab54",
  "tipo": "seguro",
  "fecha_evento": "2026-10-05",
  "categoria_id": 7,
  "descripcion": "La persona utiliza correctamente su protección.",
  "involucrados": [],
  "externos": [{"nombre": "Visitante", "empresa": ""}]
}
```

- JSON acepta la lista directamente. Multipart usa `externos` como JSON serializado, igual que `involucrados`. Para un externo existente: `[{"id":7}]`. Reintentos con el mismo UUID y contenido no crean otra persona.
- Config agrega `externos: [{id,nombre,empresa,activo}]` activos de la empresa. Detalle agrega `externos: [{id,nombre,empresa}]`, visible al reportante y al administrador; otros empleados involucrados mantienen su vista personal restringida.
- Los externos no tienen acceso propio a la app. El reportante ve estos eventos en Mis reportes; no se agregan a su historial como involucrado por haberlos informado.
- Ranking agrega `rankings_externos` con la misma separación seguro/inseguro: `{externo_id,nombre,empresa,cantidad,posicion}`. Los rankings de empleados no cambian. Los totales incluyen eventos que solo tienen externos.
- Panel: Personas externas permite crear, editar y desactivar con auditoría; cada persona tiene enlace a su historial (`externo_id`). Desactivar conserva el historial; editar la ficha no reescribe nombres guardados en eventos anteriores.
- Excel v2 agrega Tipo persona (`empleado`, `externo`, `mixto`, `pendiente`), IDs externos existentes, Nombre externo y Empresa externa. Para varios externos existentes se separan sus IDs con `;`; un externo nuevo necesita nombre y ningún legajo.
- Los nombres históricos sin coincidencia quedan **pendientes de identificar**. No se convierten automáticamente en externos. La plantilla v1 sigue admitida como formato de empleados.

## Contrato Flutter / frontend web

Prefijo `/api/v1/mobile/seguridad`. JWT Bearer existente en todas las rutas.

| Método | Ruta | Respuesta / función |
|---|---|---|
| GET | `/config` | Tipos, catálogos activos, compañeros elegibles, fecha Argentina y límites |
| POST | `/eventos` | Crear pendiente; JSON sin fotos o multipart |
| GET | `/eventos` | `vista=propio` (aprobados propios) o `vista=enviados` (todos sus envíos); `page` desde 1 |
| GET | `/eventos/{id}` | Detalle autorizado, involucrados visibles e IDs de fotos |
| GET | `/fotos/{id}` | JPEG privado autenticado, `Cache-Control: private, no-store` |
| GET | `/ranking?anio=2026&mes=9` | Ranking completo seguro/inseguro de la empresa; sin mes = año completo |

Historial: `{items: [...], total:45, page:1, per_page:30}`. Filtros opcionales `tipo`, `estado`, `desde`, `hasta`, `empleado_id`, `sucursal_id`, `sector_id`, `puesto_id`; nunca amplían el alcance autorizado. Fechas ISO, timestamps del servidor con `-03:00`. Config devuelve IDs, nombre, apellido, legajo y datos organizativos de empleados; no DNI/correo.

```json
{
  "envio_id": "8562f710-bf2b-46d0-90bb-dd621278ab54",
  "tipo": "inseguro",
  "fecha_evento": "2026-10-02",
  "categoria_id": 7,
  "involucrados": [10, 11],
  "advertido": "si",
  "descripcion": "Descripción de lo observado"
}
```

Multipart: `involucrados` es JSON serializado (`[10,11]`); fotos repiten clave `fotos`. Máximo 5 fotos, 5 MiB cada una, JPG/PNG/WEBP hasta 20 megapíxeles. JPEG normalizado a 1.800 px, sin EXIF. Accidente/incidente agregan `hora_evento` (`HH:MM`) y `lugar`; opcionales `clasificacion`, `atencion`, `lesion`, `parte_cuerpo` hasta 180 caracteres. Descripción hasta 8.000 caracteres.

Nueva alta: `201 {"id":123,"estado":"pendiente","repetido":false}`. Reintento idéntico: 200, mismo ID, `repetido:true`. Conservar UUID mientras no cambie el contenido (incluidas fotos); nuevo UUID al modificar. Otro contenido con misma clave: 409. No hay cola offline automática ni aprobación mobile. Si se reintenta un evento ya revisado, consultar el detalle para su estado actual.

Errores `{error:"mensaje"}`: 400 validación, 401 sesión, 403 alcance, 404 inexistente/no autorizado, 409 conflicto/revisión desactualizada, 413 tamaño.

Ranking: `{anio:2026,mes:9,rankings:{seguro:[{empleado_id:10,nombre:"Apellido Nombre",legajo:"0010",cantidad:3,posicion:1}],inseguro:[]},eventos:[{tipo:"seguro",cantidad:3}]}`. Panel agrega estadísticas de accidentes/incidentes y filtros organizativos históricos.

## Pruebas

### Dashboard administrativo

Acceso: **Seguridad e Higiene → Dashboard de seguridad**, ruta `/seguridad-higiene/dashboard`.
Vistas: Inseguros, Seguros, Indicadores y Resumen. Fechas por evento, filtros de sucursal,
sector y puesto históricos. Los totales y gráficos usan eventos aprobados de la empresa
autorizada; los indicadores de días sin accidentes consideran pendientes y aprobados.
Los totales y categorías cuentan eventos únicos; los puestos cuentan
participaciones de empleados. Un mismo evento puede incluir varias personas.
Los rankings de empleados y externos permanecen separados. Los externos no tienen
alcance organizativo propio. El CSV respeta el período, estado, tipo y filtros de la vista.
Las cuatro vistas incluyen detalle paginado y acceso a reportes/fotos, impresión y PDF
mediante el navegador. El resumen completa con cero los meses sin reportes aprobados.

Ejecutar `scripts/migrate_20261005_02_seguridad_dashboard.py` antes de desplegar el código
en una base nueva. La migración es aditiva e idempotente; no establece fechas por defecto.
En Indicadores, usuarios con permiso de edición pueden guardar el inicio del registro
completo de accidentes para su empresa. Queda auditado. Sin esa fecha se calcula la racha
actual si existe un accidente pendiente o aprobado; el récord requiere inicio confiable.
Se calculan hasta «Hasta», independientemente de «Desde», y con el alcance organizativo
seleccionado. Los accidentes pendientes o aprobados reinician la racha; rechazados y anulados
quedan excluidos. El récord excluye los días
con accidentes; el primer tramo sin accidentes y la racha actual cuentan días transcurridos.
Los años eliminados o datos faltantes no se interpretan como ausencia de accidentes.

Pruebas: `tests/test_seguridad_dashboard.py` cubre conteos sin duplicación, participaciones,
alcance por empresa/sucursal, meses vacíos, estados, fechas, rachas y permisos de configuración.

### Historial con legajos y equivalencias

El importador admite respuestas de Google Forms enriquecidas con `Legajo (informado)`,
`Legajo (infractor)` y `Legajo (observado)`, junto con la hoja `Equivalencias`
(`Nombre como fue escrito`, `Legajo`, `Empleado según lista`, `Estado`, `Nota`).
Se prioriza la persona informada; los campos de rama se usan cuando esa persona está vacía.
El legajo de quien notifica nunca se utiliza como persona involucrada.
`OK` permite vincular un legajo existente de la empresa; `REVISAR` y `SIN IDENTIFICAR`
quedan pendientes incluso si tienen un legajo sugerido. Las contradicciones también
requieren corrección. No se crean empleados desde este archivo.
`EXTERNO` crea una persona con nombre y empresa opcional. Las equivalencias con el
mismo nombre de destino comparten una identidad externa dentro del lote; no se
fusionan automáticamente con homónimos del registro existente. El original Excel
y sus filas se conservan; los eventos completos ingresan pendientes de aprobación.

`SH_TEST_DB_PORT` y `SH_TEST_DB_PASSWORD` habilitan MariaDB local aislado, sin credenciales `.env`. `python -m pytest tests/test_seguridad.py -q` crea una base temporal por prueba: migración repetible, concurrencia, rollback, empresa/sucursal, privacidad, revisión, ranking, importación y panel.

Flutter: pruebas específicas de API, formulario y acceso; análisis estático y compilación web.

## Dashboard mobile — API 1.33.0

Resumen propio, comparativos anuales, indicadores de empresa/sucursal/empleado y rankings: [contrato completo para web y Flutter](seguridad_mobile_dashboard.md).


## Días sin accidentes por sucursal — 1.33.1

Desde el 06/10/2026 el indicador toma la fecha del último accidente pendiente o aprobado de cada sucursal histórica. Excluye rechazados y anulados. No necesita inicio configurado si existe accidente. Sin accidentes usa el inicio confiable, y sin ambos muestra sin datos. El récord histórico sigue requiriendo inicio confiable. El dashboard agrega una tabla por sucursal y la API móvil mantiene el alcance de la sucursal del empleado autenticado.


## Fuente actual de empleados — 1.33.2

El dashboard, rankings, filtros y CSV consultan empleados por `empleado_id`, validando la misma empresa del evento. Usan nombre, legajo, puesto, sector y sucursal actuales, incluidos empleados inactivos con reportes; un puesto no asignado queda sin puesto informado. Las tarjetas de días sin accidentes usan también la sucursal actual. El detalle/auditoría conserva los datos originales y no se modifican registros históricos ni se vinculan personas por similitud de nombres. Externos permanecen separados.

Revisión del 06/10/2026: 247 participaciones vinculadas a empleados de empresa 1; ninguna discrepancia de puesto, sector o sucursal respecto de sus fichas actuales. Legajo 2300: Gerente Operaciones, seis eventos inseguros aprobados en todo el historial. Los filtros de fecha pueden mostrar un subconjunto.


<a id="seleccion-multiple-de-externos"></a>
## Selección múltiple de externos — contrato 1.34.1

El backend ya permite varios externos por evento. Aplica a comportamientos seguros/inseguros y también a accidentes/incidentes. No requiere una nueva migración para selección múltiple si el módulo de externos ya está instalado.

1. Consultar `GET /api/v1/mobile/seguridad/config` con Bearer. `externos` contiene los externos activos de la empresa: `id`, `nombre`, `empresa`, `activo`.
2. Mostrar un buscador con selección múltiple, casillas y etiquetas para quitar personas. Conservar los seleccionados al cambiar la búsqueda; usar el ID como identidad, no el nombre.
3. Permitir agregar varias personas nuevas: nombre obligatorio (180 caracteres), empresa/procedencia opcional (180). Priorizar seleccionar una persona existente para evitar altas repetidas.
4. Enviar la lista completa en `POST /api/v1/mobile/seguridad/eventos`. Se pueden mezclar registrados, nuevos y empleados; entre 1 y 100 personas en total.

Ejemplo de comportamiento seguro con varios externos y un empleado:

```json
{
  "envio_id": "5d5d5d36-9829-4357-8eb5-084e3ac927ee",
  "tipo": "seguro",
  "fecha_evento": "2026-10-08",
  "categoria_id": 1,
  "descripcion": "Las personas utilizan los elementos de protección correspondientes.",
  "involucrados": [10],
  "externos": [
    {"id": 7},
    {"id": 12},
    {"nombre": "Visitante nuevo", "empresa": "Proveedor"},
    {"nombre": "Otra persona nueva"}
  ]
}
```

Los IDs son ilustrativos: obtener empleados, externos y categorías válidos desde config. Para informar solo externos, usar `involucrados: []`. Para un comportamiento inseguro, cambiar `tipo`, seleccionar una categoría de ese tipo y agregar `advertido: "si"` o `"no"`.

Sin fotos, enviar JSON. Con fotos, usar multipart: `externos` e `involucrados` son cada uno **un campo de texto con su array JSON serializado**; fotos bajo `fotos`. No usar `externos_id`, índices de campos ni IDs separados por coma: esos no son el contrato móvil.

El servidor rechaza externos de otra empresa, IDs inactivos en altas y repetidos dentro de la lista. También rechaza nuevos con igual nombre y empresa dentro del envío, sin distinguir mayúsculas. No vincula automáticamente un nombre nuevo con un registro existente: enviar su ID para reutilizarlo. Conservar el UUID y el contenido ante un reintento; no generar un UUID nuevo por cada intento.

La respuesta de alta incluye `id`, `estado` y `repetido`. Consultar `GET /api/v1/mobile/seguridad/eventos/{id}` para recuperar `externos: [{id,nombre,empresa}]`, incluidos los IDs asignados a los nuevos. Esta lista es visible al reportante; otros empleados involucrados tienen una vista restringida. El reportante consulta sus cargas en `GET /api/v1/mobile/seguridad/eventos?vista=enviados`.

Es un único evento con varias personas: no crear un evento por cada seleccionado. Los rankings de externos y empleados permanecen separados. La interfaz móvil debe implementar este selector; actualizar el contrato no modifica las pantallas Flutter.
