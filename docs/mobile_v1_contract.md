# Contrato API Mobile v1 (Congelado)

Fecha de corte: 2026-02-16  
Base URL local: `http://localhost:5000`  
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
  "metodos_habilitados":["qr","manual","facial"]
}
```

5. `POST /api/v1/mobile/me/qr`
- Request:
```json
{"accion":"auto","scope":"empresa","vigencia_segundos":2592000}
```
- `accion`: `ingreso`, `egreso` o `auto` (recomendado para QR unico de puerta). Si no se envia, usa `auto`.
- `scope`:
  - `empresa`: QR general para todos los empleados de la empresa (default)
  - `empleado`: QR exclusivo para el empleado autenticado
- `vigencia_segundos`: 30 a 315360000 (hasta 10 anios)
- Response 200:
```json
{
  "accion":"auto",
  "scope":"empresa",
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
- Valida geocerca GPS contra la ubicacion del QR (o sucursal asignada).
- Si esta fuera de rango, bloquea la fichada.
- Request:
```json
{
  "qr_token":"<jwt_qr_auto>",
  "fecha":"2026-02-14",
  "hora":"08:03",
  "lat":-34.6037,
  "lon":-58.3816
}
```
- `lat` y `lon` son obligatorios para validar geocerca.
- Response 201 (ingreso):
```json
{"id":15,"accion":"ingreso","estado":"ok","gps_ok":true,"distancia_m":12.4,"tolerancia_m":80.0}
```
- Response 200 (egreso):
```json
{"id":15,"accion":"egreso","estado":"ok","gps_ok":true,"distancia_m":9.8,"tolerancia_m":80.0}
```
- Response 403 (fuera de geocerca):
```json
{"error":"Ubicacion fuera del rango permitido para fichar.","gps_ok":false,"distancia_m":315.2,"tolerancia_m":80.0}
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

9. `POST /api/v1/mobile/me/fichadas/entrada`
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

10. `POST /api/v1/mobile/me/fichadas/salida`
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

11. `PUT /api/v1/mobile/me/perfil`
- Request:
```json
{"telefono":"1133344455","direccion":"Calle 123","foto":"https://.../foto.jpg"}
```
- Response 200:
```json
{"id":12,"telefono":"1133344455","direccion":"Calle 123","foto":"https://.../foto.jpg"}
```

12. `PUT /api/v1/mobile/me/password`
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
- `409`: conflicto de fichada (ej. salida ya registrada)

Formato:
```json
{"error":"mensaje"}
```

## Regla de compatibilidad

Desde esta fecha, Flutter debe integrarse solo con este contrato.  
Si cambia una clave o status code, subir version (`v2`) o registrar change log explicito.
