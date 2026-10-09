# EPP y vestimenta — API mobile 1.36.0

Base: `/api/v1/mobile/epp`. Bearer JWT del empleado en **todas** las rutas, incluidas imágenes y PDF. Empresa y empleado se obtienen del token. Respuestas privadas `Cache-Control: private, no-store`. Flutter todavía debe implementar las pantallas; este backend no modifica el proyecto Flutter.

## Pantallas

- **Mis talles**: catálogo con imagen, nombre/modelo, descripción para medir, selector de talle por artículo y medidas opcionales. Guardar individualmente; actualizar config al volver a la pantalla. Desactivar un artículo no borra perfiles ni entregas.
- **Solicitar EPP**: uno o varios artículos, cada uno con talle, cantidad y medidas. Proponer el talle guardado, pero pedir al empleado que lo confirme. Un artículo por línea (sumar cantidades), hasta 50 artículos, de 1 a 1000 unidades por línea. Motivo obligatorio. Cada artículo aplica la intersección de sector y puesto; una lista vacía significa todos. No hay stock ni descuento automático.
- **Mis pedidos**: historial paginado, detalle, corrección completa mientras esté pendiente, cancelación con motivo. No permitir editar tras aprobación. Mostrar cantidades solicitadas, aprobadas y entregadas por separado.
- **Mis entregas**: dentro del detalle del pedido, entregas con fecha, indicador de planilla firmada, PDF y resumen anual por artículo/talle/medida. Las entregas anuladas conservan el comprobante, pero se excluyen de los totales.

## Rutas

| Método | Ruta | Resultado |
|---|---|---|
| GET | `/config` | `version_contrato`, `articulos`, `talles`, `max_items:50` |
| GET | `/talles` | `{items:[...]}` de talles propios |
| PUT | `/talles` | Actualiza o quita el talle de un artículo; devuelve listado |
| GET | `/pedidos?page=1&estado=pendiente` | `{items,total,page,per_page:30}` |
| POST | `/pedidos` | `{pedido,repetido}`; 201 creado, 200 reintento |
| GET | `/pedidos/{id}` | Detalle propio, `items`, `entregas`, `historial` |
| PUT | `/pedidos/{id}` | Reemplaza todas las líneas de un pedido pendiente |
| POST | `/pedidos/{id}/acciones` | Cancelación propia, devuelve detalle |
| GET | `/resumen?anio=2026` | `{anio,items}` cantidades efectivamente entregadas ese año |
| GET | `/imagenes/articulos/{id}` | JPEG privado; disponible si `tiene_imagen=1` |
| GET | `/imagenes/firmas/{id}` | JPEG firmado de entrega propia; ID de entrega |
| GET | `/entregas/{id}/pdf` | Constancia PDF de entrega propia |

Cada artículo de config contiene `id,nombre,categoria,descripcion,activo,talles,sectores,puestos,aviso_anual,tiene_imagen`. Cargar imágenes con el mismo Bearer; no exponer tokens en URL. `aviso_anual=0` significa sin orientación; es un aviso configurable, no una cuota bloqueante.

### Guardar talle

```json
{"articulo_id":1,"talle":"XL","medidas":"Contorno de pecho: 110 cm"}
```

Para quitar el perfil: `{"articulo_id":1,"eliminar":true}`. Conserva auditoría e históricos. `talle` debe coincidir con un valor vigente del artículo, no un texto arbitrario. Máximo 300 caracteres en medidas.

### Crear pedido

```json
{
  "envio_id":"600d63e9-b0fb-46ed-aedd-3e608ab91c4e",
  "motivo":"Reposición por desgaste",
  "items":[
    {"articulo_id":1,"talle":"XL","cantidad":1,"medidas":""},
    {"articulo_id":2,"talle":"42","cantidad":1,"medidas":""}
  ]
}
```

IDs y talles son ilustrativos: usar config. Guardar UUID durante reintentos, sin cambiar el contenido. El servidor serializa altas por empleado y no duplica una solicitud por reintentos concurrentes; UUID con otro contenido devuelve 409. Se admite `accion: "borrador"` al crear o editar; requiere motivo y líneas completas, pero no inicia aprobación. `accion: "enviar"` (por defecto) pasa a pendiente. La edición requiere `revision` vigente, `motivo` y **todos** los `items` que deben permanecer; reemplaza las líneas y audita la versión anterior. Actualizar talles del perfil no modifica pedidos ni entregas históricas.

Cancelar: `{"accion":"cancelar","revision":1,"motivo":"Ya no lo necesito"}`. Solo `borrador` o `pendiente`. Estados: `borrador, pendiente, aprobado, parcial, entregado, rechazado, cancelado`. `aprobado` puede incluir aprobación parcial por cantidades; `parcial` significa entrega parcial. La aprobación se realiza desde el panel, nunca por la API del empleado. Una sola resolución del jefe directo actual o de un responsable autorizado es suficiente; no se permite autoaprobación.

## Entregas y administración

Panel `/epp/`: catálogos, categorías, talles, pedidos por empleado, resolución por cantidades, entregas parciales, PDF, foto de planilla firmada y reporte CSV por año/sucursal/empleado. Un responsable registra pedidos desde el panel y resuelve/entrega usando el mismo circuito trazable. No se carga una entrega sin pedido aprobado. Este circuito no incluye devolución física ni movimientos de stock; una entrega equivocada se anula con motivo y se vuelve a cargar correctamente.

Permisos: `epp` para consultar, crear, editar, aprobar y exportar; `epp_responsables.ver` concede alcance de Seguridad e Higiene para toda la empresa, `.editar` administra catálogo/categorías y `.crear` registra entregas. Asignar **ambos módulos** a los responsables de Seguridad e Higiene. Admin los tiene por defecto. Jefes/supervisores sin alcance global acceden solo a empleados que les reportan actualmente. Los reportes conservan la sucursal registrada en el pedido. No hay acceso entre empresas.

Cantidades aprobadas entre 0 y lo solicitado; reducción/rechazo requieren motivo. Entregar no puede superar lo aprobado pendiente. El servicio bloquea por pedido y empleado para serializar entregas y avisos anuales. Si supera el aviso orientativo, requiere observaciones justificativas y permite continuar. Una entrega guarda fecha, responsable y cantidades; el talle proviene del snapshot del pedido aprobado. La planilla firmada se adjunta como una imagen JPG/PNG/WEBP de hasta 5 MiB/20 MP, normalizada a JPEG. No se sobrescribe una firma ya adjunta. Las anulaciones conservan evidencia y auditoría.

Errores: 400 validación, 401 sesión, 403 alcance/permiso, 404 inexistente, 409 revisión/estado/clave en conflicto, 413 tamaño, 503 esquema pendiente. Conservar los datos del formulario al fallar; en 409 recargar detalle antes de decidir. No reintentar aprobaciones ni entregas con una clave nueva sin comprobar el resultado previo.

## Instalación

Ejecutar `venv\\Scripts\\python.exe scripts/migrate_20261008_02_epp.py`, reiniciar backend y configurar artículos, imágenes, talles, sectores/puestos y responsables. La migración es aditiva e idempotente, crea ocho tablas y categorías iniciales EPP/Ropa/Calzado por empresa existente. No importa entregas ficticias ni altera empleados. Empresas nuevas pueden crear sus categorías en el panel.
