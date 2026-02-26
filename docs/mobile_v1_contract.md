# Contrato API Mobile v1 (Congelado)

Version de contrato: 1.6.0  
Fecha de corte: 2026-02-25  
Base URL local: `http://localhost:5000`  
Base URL produccion: `https://control-asistencia-backend-8gle.onrender.com`  
Prefijo: `/api/v1/mobile`

Este documento fija el contrato para Flutter.  
Fuente tecnica: `routes/mobile_v1_routes.py`.

## Autenticacion

- Tipo: `Bearer JWT`
- Header: `Authorization: Bearer <token>`
- Login: `POST /auth/login`
- Refresh: `POST /auth/refresh`

## Endpoints

1. `POST /api/v1/mobile/auth/login`
- Request:
```json
{"dni":"30111222","password":"secreta123"}
```
- Response 200:
```json
{
  "token":"<jwt>",
  "empleado":{"id":12,"dni":"30111222","nombre":"Ana","apellido":"Lopez","empresa_id":1}
}
```

2. `POST /api/v1/mobile/auth/refresh`
- Response 200:
```json
{"token":"<jwt>"}
```

3. `GET /api/v1/mobile/me`
- Response 200: perfil de empleado autenticado.

4. `GET /api/v1/mobile/me/config-asistencia`
- Response 200:
```json
{
  "empresa_id":1,
  "requiere_qr":false,
  "requiere_foto":false,
  "requiere_geo":false,
  "tolerancia_global":5,
  "cooldown_scan_segundos":60,
  "metodos_habilitados":["qr","manual","facial"]
}
```

5. `POST /api/v1/mobile/me/qr`
- Request:
```json
{"accion":"auto","scope":"empresa","tipo_marca":"jornada","vigencia_segundos":2592000}
```
- `accion`: `ingreso`, `egreso` o `auto` (recomendado para QR unico de puerta). Si no se envia, usa `auto`.
- `scope`:
  - `empresa`: QR general para todos los empleados de la empresa (default)
  - `empleado`: QR exclusivo para el empleado autenticado
- `tipo_marca`:
  - `jornada` (default)
  - `desayuno`
  - `almuerzo`
  - `merienda`
  - `otro`
- `vigencia_segundos`: 30 a 315360000 (hasta 10 anios)
- Response 200:
```json
{
  "accion":"auto",
  "scope":"empresa",
  "tipo_marca":"jornada",
  "empresa_id":1,
  "empleado_id":null,
  "vigencia_segundos":2592000,
  "expira_at":"2026-02-16T15:02:00Z",
  "qr_token":"<jwt_qr>",
  "qr_png_base64":"data:image/png;base64,iVBORw0K..."
}
```

6. `POST /api/v1/mobile/me/fichadas/scan`
- Caso recomendado para QR unico de puerta.
- El backend detecta empleado por JWT y decide si corresponde `ingreso` o `egreso`.
- La decision automatica se basa en la ultima marca del dia (soporta horario cortado con multiples ciclos).
- Valida geocerca GPS contra la ubicacion del QR (o sucursal asignada).
- Si esta fuera de rango, bloquea la fichada.
- Request:
```json
{
  "qr_token":"<jwt_qr_auto>",
  "fecha":"2026-02-14",
  "hora":"08:03",
  "tipo_marca":"almuerzo",
  "lat":-34.6037,
  "lon":-58.3816
}
```
- `lat` y `lon` son obligatorios para validar geocerca.
- `tipo_marca` es opcional; si el QR contiene tipo, prevalece el del QR.
- Response 201 (ingreso):
```json
{"id":15,"marca_id":1201,"accion":"ingreso","tipo_marca":"almuerzo","estado":"ok","gps_ok":true,"distancia_m":12.4,"tolerancia_m":80.0,"total_marcas_dia":1}
```
- Response 200 (egreso):
```json
{"id":15,"marca_id":1202,"accion":"egreso","tipo_marca":"almuerzo","estado":"ok","gps_ok":true,"distancia_m":9.8,"tolerancia_m":80.0,"total_marcas_dia":2}
```
- Response 403 (fuera de geocerca):
```json
{
  "error":"Ubicacion fuera del rango permitido para fichar.",
  "gps_ok":false,
  "distancia_m":315.2,
  "tolerancia_m":80.0,
  "alerta_fraude":true,
  "evento_id":901
}
```
- Response 409 (cooldown anti duplicado):
```json
{
  "error":"Escaneo duplicado detectado. Espere 42 segundos para volver a fichar.",
  "code":"scan_cooldown",
  "cooldown_segundos_restantes":42
}
```

7. `GET /api/v1/mobile/me/horario-esperado?fecha=YYYY-MM-DD`
- Response 200:
```json
{
  "tiene_excepcion": false,
  "bloques":[{"entrada":"08:00","salida":"16:00"}],
  "tolerancia": 5
}
```
- Response 404: `{"error":"sin horario esperado"}`

8. `GET /api/v1/mobile/me/asistencias?desde=&hasta=&page=&per=`
- Response 200:
```json
{
  "items":[
    {
      "id":1,
      "fecha":"2026-02-14",
      "hora_entrada":"08:01",
      "hora_salida":"16:04",
      "metodo_entrada":"qr",
      "metodo_salida":"qr",
      "estado":"ok",
      "observaciones":null,
      "gps_ok_entrada":true,
      "gps_ok_salida":true,
      "gps_distancia_entrada_m":12.4,
      "gps_distancia_salida_m":9.8,
      "gps_tolerancia_entrada_m":80.0,
      "gps_tolerancia_salida_m":80.0
    }
  ],
  "page":1,
  "per_page":20,
  "total":1
}
```

9. `GET /api/v1/mobile/me/eventos-seguridad?page=&per=&tipo_evento=`
- Lista intentos/eventos de seguridad del empleado autenticado (por ejemplo, QR fuera de geocerca).
- Response 200:
```json
{
  "items":[
    {
      "id":901,
      "tipo_evento":"qr_geo_fuera_rango",
      "severidad":"alta",
      "alerta_fraude":true,
      "fecha":"2026-02-18T15:24:10",
      "fecha_operacion":"2026-02-18",
      "hora_operacion":"15:24",
      "lat":-34.6037,
      "lon":-58.3816,
      "ref_lat":-34.6020,
      "ref_lon":-58.3800,
      "distancia_m":315.2,
      "tolerancia_m":80.0,
      "sucursal_id":3
    }
  ],
  "page":1,
  "per_page":20,
  "total":1
}
```
- Response 500:
```json
{"error":"No se pudo obtener eventos de seguridad."}
```

10. `GET /api/v1/mobile/me/marcas?desde=&hasta=&page=&per=`
- Lista paginada de marcas atomicas del empleado autenticado (ingreso/egreso).
- Response 200:
```json
{
  "items":[
    {
      "id":1201,
      "asistencia_id":15,
      "fecha":"2026-02-14",
      "hora":"08:03",
      "accion":"ingreso",
      "metodo":"qr",
      "tipo_marca":"almuerzo",
      "estado":"ok",
      "observaciones":"Ingreso principal",
      "lat":-34.6037,
      "lon":-58.3816,
      "gps_ok":true,
      "gps_distancia_m":12.4,
      "gps_tolerancia_m":80.0,
      "fecha_creacion":"2026-02-14T08:03:10"
    }
  ],
  "page":1,
  "per_page":20,
  "total":1
}
```

11. `POST /api/v1/mobile/me/fichadas/entrada` (deprecated)
- Mantener solo por compatibilidad retroactiva.
- Para nuevas integraciones usar `POST /api/v1/mobile/me/fichadas/scan`.
- Request:
```json
{
  "fecha":"2026-02-14",
  "metodo":"qr",
  "qr_token":"<jwt_qr_ingreso>",
  "hora_entrada":"08:03",
  "lat":-34.6037,
  "lon":-58.3816,
  "foto":null,
  "observaciones":"Ingreso principal"
}
```
- Response 201:
```json
{"id": 15, "estado":"ok"}
```

12. `POST /api/v1/mobile/me/fichadas/salida` (deprecated)
- Mantener solo por compatibilidad retroactiva.
- Para nuevas integraciones usar `POST /api/v1/mobile/me/fichadas/scan`.
- Request:
```json
{
  "fecha":"2026-02-14",
  "metodo":"qr",
  "qr_token":"<jwt_qr_egreso>",
  "hora_salida":"16:02",
  "lat":-34.6037,
  "lon":-58.3816
}
```
- Response 200:
```json
{"id": 15, "estado":"ok"}
```

13. `PUT /api/v1/mobile/me/perfil`
- Request:
```json
{"telefono":"1133344455","direccion":"Calle 123","foto":"https://.../foto.jpg"}
```
- Response 200:
```json
{"id":12,"telefono":"1133344455","direccion":"Calle 123","foto":"https://.../foto.jpg"}
```

14. `PUT /api/v1/mobile/me/password`
- Request:
```json
{"password_actual":"secreta123","password_nueva":"nueva1234"}
```
- Response 200:
```json
{"ok":true}
```

## Errores estandar

- `400`: validacion de payload/formato
- `401`: login/token invalido o vencido
- `403`: fuera de geocerca o usuario no permitido
- `404`: recurso no encontrado (ej. sin horario esperado, sin entrada para salida)
- `409`: conflicto de fichada (ej. salida ya registrada o cooldown por doble scan)
- `500`: error interno inesperado

Formato base:
```json
{"error":"mensaje"}
```
Formato recomendado para cooldown scan:
```json
{"error":"...","code":"scan_cooldown","cooldown_segundos_restantes":42}
```

## Regla de compatibilidad

Desde esta fecha, Flutter debe integrarse solo con este contrato.  
Si cambia una clave o status code, subir version (`v2`) o registrar change log explicito.

## Change log

### 1.6.0 (2026-02-25)
- `GET /api/v1/mobile/me/config-asistencia` agrega:
  - `cooldown_scan_segundos`
- `POST /api/v1/mobile/me/fichadas/scan` agrega en `409` por doble scan:
  - `code = "scan_cooldown"`
  - `cooldown_segundos_restantes`
- Objetivo: permitir mensaje UX claro en Flutter sin parsear texto libre.

### 1.5.0 (2026-02-24)
- Se mantiene como endpoint recomendado `POST /api/v1/mobile/me/fichadas/scan`.
- Se marcan como `deprecated` (compatibilidad legacy):
  - `POST /api/v1/mobile/me/fichadas/entrada`
  - `POST /api/v1/mobile/me/fichadas/salida`
- Se agrega base URL de produccion:
  - `https://control-asistencia-backend-8gle.onrender.com`
- No hay cambios de payload ni status codes en endpoints activos.
