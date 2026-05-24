# Contrato API Externa v1

Version de contrato: 1.0.0
Fecha de corte: 2026-05-22
Base URL local: `http://localhost:5000`
Base URL produccion: `https://control-asistencia.up.railway.app`
Prefijo: `/api/v1/external`

Este documento fija el contrato para aplicaciones externas que necesiten consultar empresas, sucursales y empleados.
Fuente tecnica: `routes/external_api_routes.py`.

## Autenticacion

Todas las rutas requieren API key.

Header recomendado:

```http
X-API-Key: <EXTERNAL_API_KEY>
```

Tambien se acepta:

```http
Authorization: Bearer <EXTERNAL_API_KEY>
```

La clave se configura en el backend:

```env
EXTERNAL_API_KEY=clave_larga_y_segura
```

La clave no esta incluida en este contrato. Debe crearse y guardarse como variable
de entorno en Railway, en el servicio del backend:

```text
EXTERNAL_API_KEY=<clave_larga_y_segura>
```

La misma clave se comparte con la app externa por un canal seguro y esa app debe
guardarla como secreto de entorno. No enviar la clave por query string, no
exponerla en frontend publico y no subirla al repositorio.

## Respuestas de error

### 401 API key ausente o invalida

```json
{
  "error": "API key invalida o ausente."
}
```

### 503 API key no configurada en backend

```json
{
  "error": "EXTERNAL_API_KEY no configurada."
}
```

### 400 Parametro invalido

```json
{
  "error": "estado invalido. Use activo, inactivo, suspendido o all."
}
```

## Endpoints

### 1. `GET /api/v1/external/catalogo`

Endpoint recomendado cuando la app externa necesita traer empresas, sucursales y empleados en una sola llamada.

#### Query params

| Parametro | Tipo | Default | Descripcion |
|---|---:|---:|---|
| `empresa_id` | int | - | Filtra sucursales y empleados por empresa. |
| `sucursal_id` | int/csv/repetible | - | Filtra empleados por ID de sucursal. |
| `sucursales_id` | int/csv/repetible | - | Alias de `sucursal_id`. |
| `sucursal` | string/csv/repetible | - | Filtra empleados por nombre de sucursal. |
| `sucursal_nombre` | string/csv/repetible | - | Alias de `sucursal`. |
| `sucursales` | string/csv/repetible | - | Alias de `sucursal`. |
| `puesto_id` | int/csv/repetible | - | Filtra empleados por ID de puesto. |
| `puestos_id` | int/csv/repetible | - | Alias de `puesto_id`. |
| `tipo_empleado` | string/csv/repetible | - | Filtra empleados por nombre de puesto. |
| `tipo` | string/csv/repetible | - | Alias de `tipo_empleado`. |
| `puesto` | string/csv/repetible | - | Alias de `tipo_empleado`. |
| `puestos` | string/csv/repetible | - | Alias de `tipo_empleado`. |
| `estado` | string/csv/repetible | - | Valores: `activo`, `inactivo`, `suspendido`, `all`. |
| `estados` | string/csv/repetible | - | Alias de `estado`. |
| `activo` | bool/all | `1` | Si no se envia `estado`, filtra empleados activos. Valores: `1`, `0`, `all`. |
| `empresas_activa` | bool/all | `1` | Filtra empresas activas. Valores: `1`, `0`, `all`. |
| `sucursales_activa` | bool/all | `1` | Filtra sucursales activas. Valores: `1`, `0`, `all`. |
| `q` | string | - | Busca empleados por apellido, nombre, DNI o legajo. |
| `page` | int | `1` | Pagina de empleados. |
| `per_page` | int | `100` | Empleados por pagina. Maximo `500`. |
| `per` | int | - | Alias de `per_page`. |
| `limit` | int | - | Alias de `per_page`. |

Notas:
- `tipo_empleado` consulta el puesto principal y tambien puestos adicionales del empleado.
- Los filtros por nombre no distinguen mayusculas/minusculas.
- Los valores se pueden enviar separados por coma o repitiendo el parametro.
- `choferes` y `ayudantes` tambien matchean `chofer` y `ayudante`.
- Si se envia `estado`, el filtro `activo` no se aplica, salvo `estado=all&activo=1`.

#### Ejemplo Dolores

```http
GET /api/v1/external/catalogo?sucursal=Dolores&tipo_empleado=choferes,ayudantes&estado=activo&per_page=500
X-API-Key: <EXTERNAL_API_KEY>
```

#### Ejemplo Casa Central

```http
GET /api/v1/external/catalogo?sucursal=Casa%20Central&tipo_empleado=choferes,ayudantes&estado=activo&per_page=500
X-API-Key: <EXTERNAL_API_KEY>
```

#### Response 200

```json
{
  "empresas": [
    {
      "id": 1,
      "razon_social": "Empresa SA",
      "nombre_fantasia": "Empresa",
      "cuit": "30-00000000-1",
      "email": "info@empresa.com",
      "telefono": "123456",
      "direccion": "Calle 123",
      "activa": true
    }
  ],
  "sucursales": [
    {
      "id": 10,
      "empresa_id": 1,
      "empresa_nombre": "Empresa SA",
      "nombre": "Dolores",
      "direccion": "Ruta 2",
      "latitud": -36.3132,
      "longitud": -57.6791,
      "radio_permitido_m": 150,
      "activa": true
    }
  ],
  "empleados": [
    {
      "id": 7,
      "empresa_id": 1,
      "empresa_nombre": "Empresa SA",
      "sucursal_id": 10,
      "sucursal_nombre": "Dolores",
      "sector_id": 3,
      "sector_nombre": "Operaciones",
      "puesto_id": 2,
      "puesto_nombre": "Chofer",
      "puestos_adicionales_ids": [3],
      "puestos_adicionales_nombres": ["Ayudante"],
      "reporta_a_empleado_id": 1,
      "reporta_a_nombre": "Gomez Maria",
      "legajo": "L001",
      "dni": "30123456",
      "cuil": "20-30123456-7",
      "nombre": "Juan",
      "apellido": "Perez",
      "email": "juan.perez@empresa.com",
      "telefono": "11223344",
      "fecha_ingreso": "2024-01-15",
      "fecha_baja": null,
      "tipo_contrato": "efectivo",
      "modalidad": "presencial",
      "categoria": "C",
      "cod_chess_erp": 1234,
      "estado": "activo",
      "activo": true,
      "codigo_postal": "7100",
      "localidad_nombre": "Dolores"
    }
  ],
  "counts": {
    "empresas": 1,
    "sucursales": 1,
    "empleados": 1
  },
  "empleados_pagination": {
    "page": 1,
    "per_page": 500,
    "total": 1,
    "pages": 1
  }
}
```

### 2. `GET /api/v1/external/empresas`

Lista empresas.

#### Query params

| Parametro | Tipo | Default | Descripcion |
|---|---:|---:|---|
| `activa` | bool/all | `1` | `1` activas, `0` inactivas, `all` todas. |

#### Response 200

```json
{
  "data": [
    {
      "id": 1,
      "razon_social": "Empresa SA",
      "nombre_fantasia": "Empresa",
      "cuit": "30-00000000-1",
      "email": "info@empresa.com",
      "telefono": "123456",
      "direccion": "Calle 123",
      "activa": true
    }
  ],
  "count": 1
}
```

### 3. `GET /api/v1/external/sucursales`

Lista sucursales.

#### Query params

| Parametro | Tipo | Default | Descripcion |
|---|---:|---:|---|
| `empresa_id` | int | - | Filtra por empresa. |
| `activa` | bool/all | `1` | `1` activas, `0` inactivas, `all` todas. |

#### Response 200

```json
{
  "data": [
    {
      "id": 10,
      "empresa_id": 1,
      "empresa_nombre": "Empresa SA",
      "nombre": "Dolores",
      "direccion": "Ruta 2",
      "latitud": -36.3132,
      "longitud": -57.6791,
      "radio_permitido_m": 150,
      "activa": true
    }
  ],
  "count": 1
}
```

### 4. `GET /api/v1/external/empleados`

Lista empleados. Usa los mismos filtros de empleados que `/catalogo`.

#### Ejemplo

```http
GET /api/v1/external/empleados?sucursal=Dolores&tipo_empleado=choferes,ayudantes&estado=activo&per_page=500
X-API-Key: <EXTERNAL_API_KEY>
```

#### Response 200

```json
{
  "data": [
    {
      "id": 7,
      "empresa_id": 1,
      "empresa_nombre": "Empresa SA",
      "sucursal_id": 10,
      "sucursal_nombre": "Dolores",
      "sector_id": 3,
      "sector_nombre": "Operaciones",
      "puesto_id": 2,
      "puesto_nombre": "Chofer",
      "puestos_adicionales_ids": [3],
      "puestos_adicionales_nombres": ["Ayudante"],
      "reporta_a_empleado_id": 1,
      "reporta_a_nombre": "Gomez Maria",
      "legajo": "L001",
      "dni": "30123456",
      "cuil": "20-30123456-7",
      "nombre": "Juan",
      "apellido": "Perez",
      "email": "juan.perez@empresa.com",
      "telefono": "11223344",
      "fecha_ingreso": "2024-01-15",
      "fecha_baja": null,
      "tipo_contrato": "efectivo",
      "modalidad": "presencial",
      "categoria": "C",
      "cod_chess_erp": 1234,
      "estado": "activo",
      "activo": true,
      "codigo_postal": "7100",
      "localidad_nombre": "Dolores"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 500,
    "total": 1,
    "pages": 1
  }
}
```

## Ejemplos de integracion

### curl

```bash
curl -H "X-API-Key: <EXTERNAL_API_KEY>" \
  "https://control-asistencia.up.railway.app/api/v1/external/catalogo?sucursal=Dolores&tipo_empleado=choferes,ayudantes&estado=activo&per_page=500"
```

### JavaScript / Fetch

```js
const url = new URL("https://control-asistencia.up.railway.app/api/v1/external/catalogo");
url.searchParams.set("sucursal", "Dolores");
url.searchParams.set("tipo_empleado", "choferes,ayudantes");
url.searchParams.set("estado", "activo");
url.searchParams.set("per_page", "500");

const res = await fetch(url, {
  headers: {
    "X-API-Key": "<EXTERNAL_API_KEY>"
  }
});

if (!res.ok) {
  throw new Error(`API externa error ${res.status}: ${await res.text()}`);
}

const data = await res.json();
console.log(data.empresas);
console.log(data.sucursales);
console.log(data.empleados);
```

### Python / requests

```python
import requests

res = requests.get(
    "https://control-asistencia.up.railway.app/api/v1/external/catalogo",
    headers={"X-API-Key": "<EXTERNAL_API_KEY>"},
    params={
        "sucursal": "Dolores",
        "tipo_empleado": "choferes,ayudantes",
        "estado": "activo",
        "per_page": 500,
    },
    timeout=30,
)
res.raise_for_status()
data = res.json()
```

## Reglas operativas

- Solo usar HTTPS en produccion.
- Guardar la API key como secreto de entorno en la app externa.
- No exponer la API key en frontend publico, URL, logs ni repositorios.
- Paginacion: si `empleados_pagination.pages` es mayor a `1`, pedir las paginas siguientes con `page=2`, `page=3`, etc.
- El contrato es solo lectura. No crea, edita ni elimina registros.
