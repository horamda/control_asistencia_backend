# Carga de resultados de KPIs desde otra app

Endpoint: `POST /api/v1/external/kpis/resultados`.
Disponible una vez desplegada esta version. Usa las tablas de KPIs existentes;
no requiere una migracion nueva si el modulo de KPIs ya esta instalado.

## Habilitar la integracion

1. Configurar las credenciales del usuario tecnico segun
   [Autenticacion de la API externa](external_api_contract.md#autenticacion).
2. Configurar `EXTERNAL_API_KPI_WRITE_ENABLED=1` en el backend y reiniciar/desplegar.
3. Solicitar un token nuevo mediante `POST /api/v1/external/auth/token`.
   La respuesta y el token incluiran `scope: "external:read reports:read kpis:write"`.
4. Enviar `Authorization: Bearer <TOKEN>` en cada carga.

La escritura esta deshabilitada por defecto. Los tokens anteriores de lectura y
las claves estaticas no autorizan este endpoint. Al deshabilitar la variable,
la escritura se bloquea inmediatamente para las solicitudes del proceso que
tenga la nueva configuracion, incluso con tokens que aun no vencieron.
Las credenciales tecnicas existentes son globales: habilitar esta opcion permite
que ese usuario cargue KPIs de cualquier empresa. No hay usuarios ni permisos por
empresa separados en esta integracion. Mantener las credenciales en el servidor
de la app emisora, no en su JavaScript publico.

## Datos previos

- Empleado activo, con legajo y sector asignados dentro de la empresa.
- KPI activo definido para el sector actual del empleado.
- Objetivos, unidad y tipo de acumulacion configurados en el panel.

No se crean empleados, definiciones ni objetivos mediante este endpoint. Los
resultados guardados alimentan las consultas existentes del panel y de la app
del empleado; se veran al volver a consultar/actualizar esas pantallas.

## Solicitud

```http
POST /api/v1/external/kpis/resultados
Authorization: Bearer <TOKEN>
Content-Type: application/json
```

```json
{
  "empresa_id": 1,
  "resultados": [
    {"legajo": "001", "fecha": "2026-09-14", "codigo_kpi": "BULTOS", "valor": 125},
    {"legajo": "002", "fecha": "2026-09-14", "codigo_kpi": "CALIDAD", "valor": "98.7500"}
  ]
}
```

| Campo | Regla |
| --- | --- |
| `empresa_id` | Entero positivo, no texto. Una empresa por lote. |
| `resultados` | Lista de 1 a 1.000 objetos. |
| `legajo` | Texto; conservar ceros iniciales. Se eliminan espacios de los extremos. |
| `fecha` | Dia operativo `YYYY-MM-DD`, existente, desde el anio 1000 y no futuro segun la fecha del servidor. |
| `codigo_kpi` | Texto, se normaliza a mayusculas. Se resuelve dentro del sector del empleado. |
| `valor` | Numero JSON o texto decimal con punto, hasta cuatro decimales. Rango: -9999999999.9999 a 9999999999.9999. No admite booleanos, null, NaN ni infinito. |

Enviar el resultado del dia. Para KPIs de tipo suma, enviar acumulados mensuales
cada dia produciria una suma incorrecta. Si solo se dispone de un total mensual,
hay que acordar su representacion antes de usar esta carga diaria.

## Guardado y reintentos

- Valida el lote completo antes de escribir. Una fila invalida rechaza todo el lote.
- Si ya existe el mismo empleado, KPI y fecha, reemplaza su valor.
- Reenviar un lote no crea duplicados. Una correccion posterior prevalece.
- No elimina registros de otros dias, otros KPIs ni otros empleados.
- Repetir empleado/KPI/fecha dentro del mismo lote es un error.
- El guardado usa una transaccion; ante errores de base de datos se intenta rollback.
- Ante un corte de conexion se puede reenviar exactamente el mismo lote.
- Limite de frecuencia: 30 solicitudes por minuto, con la clave de limitacion
  configurada en la aplicacion.

Respuesta `200`:

```json
{"empresa_id": 1, "recibidos": 2, "guardados": 2}
```

`guardados` cuenta las filas procesadas, incluyendo actualizaciones y reenvios
sin cambios. No distingue filas nuevas de existentes.

Respuesta `422` (numero de fila desde 1 dentro de `resultados`):

```json
{
  "error": "Lote rechazado. Corrija las filas indicadas y reenvie el lote completo.",
  "guardados": 0,
  "detalle_errores": [
    {"fila": 2, "error": "KPI no encontrado o inactivo para el sector del empleado."}
  ]
}
```

| Estado | Significado |
| --- | --- |
| 400 | JSON mal formado, empresa invalida o cantidad de filas fuera de limites. |
| 401 | Autenticacion ausente, invalida o token vencido. |
| 403 | Escritura deshabilitada o token sin `kpis:write`. |
| 415 | Content-Type distinto de JSON. |
| 422 | Datos invalidos; ningun resultado guardado. |
| 429 | Limite de solicitudes alcanzado. |
| 500 | Error interno; es posible reintentar el mismo lote. |
| 503 | Autenticacion externa sin configurar. |

## Ejemplo desde el servidor de otra app (JavaScript)

```javascript
const base = process.env.FICHAYA_BASE_URL;
const auth = await fetch(`${base}/api/v1/external/auth/token`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    username: process.env.FICHAYA_USERNAME,
    password: process.env.FICHAYA_PASSWORD
  })
});
if (!auth.ok) throw new Error(`Error de autenticacion: ${auth.status}`);
const { access_token } = await auth.json();

const response = await fetch(`${base}/api/v1/external/kpis/resultados`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${access_token}`
  },
  body: JSON.stringify({
    empresa_id: 1,
    resultados: [
      { legajo: "001", fecha: "2026-09-14", codigo_kpi: "BULTOS", valor: 125 }
    ]
  })
});
const result = await response.json();
if (!response.ok) throw new Error(JSON.stringify(result));
console.log(result);
```

El ejemplo solicita un token por simplicidad. En produccion se puede reutilizar
hasta su vencimiento y solicitar otro al recibir 401. No reintentar errores 400/422
sin corregir sus datos.
