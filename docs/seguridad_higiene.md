# Seguridad e Higiene — API 1.31.0

## Activación

1. Ejecutar `python scripts/migrate_20261002_01_seguridad_higiene.py` antes de publicar backend. Migración aditiva, repetible, con catálogos iniciales para empresas existentes. Repetir no borra ni reactiva categorías.
2. Asignar el módulo **Seguridad e Higiene** (`seguridad_higiene`) a usuarios elegidos. Admin lo incluye por defecto. Permisos independientes: `ver`, `crear`, `editar`, `aprobar`, `eliminar` (anular), `exportar`. Revisores necesitan `ver` + `aprobar`; no hay un rol fijo obligatorio.
3. Revisar catálogos en `/seguridad-higiene/catalogos`. Las empresas creadas posteriormente cargan sus catálogos desde el panel.
4. Publicar backend antes de Flutter. La app muestra **Seguridad e Higiene** junto a los demás accesos.
5. Subir el Excel en **Importar histórico**, resolver inconsistencias y crear eventos pendientes. Aprobarlos desde la bandeja.

Fotografías, Excel original y filas se almacenan en MySQL; incluir tablas `sh_*` en backups. El proxy debe admitir 27 MB por envío. Importador: XLSX hasta 10 MB, 50 MB descomprimidos, 5.000 respuestas.

## Reglas y privacidad

- Tipos separados: `seguro`, `inseguro`, `incidente` (sin lesión), `accidente`.
- El empleado reporta sobre sí mismo o compañeros activos de su sucursal. Administración selecciona dentro de su empresa; importación admite empleados históricos inactivos.
- Entre 1 y 100 involucrados únicos. Se conservan nombre, legajo, sucursal, sector y puesto al registrarlos.
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

`SH_TEST_DB_PORT` y `SH_TEST_DB_PASSWORD` habilitan MariaDB local aislado, sin credenciales `.env`. `python -m pytest tests/test_seguridad.py -q` crea una base temporal por prueba: migración repetible, concurrencia, rollback, empresa/sucursal, privacidad, revisión, ranking, importación y panel.

Flutter: pruebas específicas de API, formulario y acceso; análisis estático y compilación web.
