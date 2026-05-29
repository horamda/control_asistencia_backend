# Contrato API Mobile v1

Version de contrato: 1.21.5
Fecha de corte: 2026-05-28
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

---

## Endpoints

### Versión de la app

#### 0. `GET /api/v1/mobile/version?platform=android`
- Público — **no requiere token**.
- Devuelve la versión mínima y recomendada de la app para la plataforma dada.
- `platform`: `"android"` o `"ios"` (default `"android"` si se omite o es inválido).
- Response 200:
```json
{
  "ok": true,
  "platform": "android",
  "version_minima": "1.19.0",
  "version_recomendada": "1.20.4",
  "url_descarga": "https://play.google.com/store/apps/details?id=com.example.app",
  "mensaje": null
}
```
- `version_minima`: versión por debajo de la cual la app debe bloquearse y forzar actualización.
- `version_recomendada`: versión sugerida; la app puede mostrar un banner no bloqueante.
- `url_descarga`: URL de la tienda, o `null` si no está configurado.
- `mensaje`: texto libre opcional para mostrar al usuario (novedad, aviso de mantenimiento, etc.), o `null`.
- Si no hay configuración en base para la plataforma, devuelve `version_minima: "1.0.0"`, `version_recomendada: "1.0.0"` y el resto `null`.

---

### Auth

#### 1. `POST /api/v1/mobile/auth/login`
- Request — campos obligatorios + campos opcionales de telemetría:
```json
{
  "dni": "30111222",
  "password": "secreta123",
  "platform": "android",
  "device_model": "Samsung Galaxy A54",
  "app_version": "1.20.4"
}
```
  | Campo | Tipo | Requerido | Notas |
  |---|---|---|---|
  | `dni` | string | Sí | |
  | `password` | string | Sí | |
  | `platform` | string | No | `"android"` o `"ios"`. Si se omite se guarda como nulo. |
  | `device_model` | string | No | Modelo del dispositivo (ej. `"Samsung Galaxy A54"`). |
  | `app_version` | string | No | Versión instalada de la app (ej. `"1.20.4"`). |

- Response 200:
```json
{
  "token": "<jwt>",
  "empleado": {
    "id": 12,
    "dni": "30111222",
    "nombre": "Ana",
    "apellido": "Lopez",
    "empresa_id": 1,
    "foto": "https://.../30111222.jpg",
    "imagen_version": "1709294400"
  }
}
```
- El JWT incluye internamente `sesion_id` para tracking de último request. Flutter no necesita leerlo.

#### 2. `POST /api/v1/mobile/auth/refresh`
- Actualiza `fecha_ultimo_request` de la sesión en curso (si el token tiene `sesion_id`).
- No requiere body.
- Response 200:
```json
{"token": "<jwt>"}
```
- El nuevo token mantiene el mismo `sesion_id` de la sesión original.

#### Flujo recomendado Flutter — Login con telemetría

```dart
import 'package:device_info_plus/device_info_plus.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'dart:io' show Platform;

Future<Map<String, String>> buildLoginExtras() async {
  final pkg = await PackageInfo.fromPlatform();
  final deviceInfo = DeviceInfoPlugin();
  String model = '';
  if (Platform.isAndroid) {
    final info = await deviceInfo.androidInfo;
    model = '${info.brand} ${info.model}';
  } else if (Platform.isIOS) {
    final info = await deviceInfo.iosInfo;
    model = info.utsname.machine;
  }
  return {
    'platform': Platform.isAndroid ? 'android' : 'ios',
    'device_model': model,
    'app_version': pkg.version,
  };
}

// En el servicio de auth, agregar los extras al body del login:
final extras = await buildLoginExtras();
final body = {'dni': dni, 'password': password, ...extras};
```
- `device_info_plus` ya está disponible si usás `package_info_plus`. Verificar en `pubspec.yaml`.

---

### Perfil

#### 3. `GET /api/v1/mobile/me`
- Response 200: perfil completo del empleado autenticado (incluye `imagen_version` para cache busting de foto).

#### 4. `GET /api/v1/mobile/me/config-asistencia`
- Response 200:
```json
{
  "empresa_id":1,
  "requiere_qr":false,
  "requiere_foto":false,
  "requiere_geo":false,
  "tolerancia_global":5,
  "cooldown_scan_segundos":60,
  "intervalo_minimo_fichadas_minutos":60,
  "metodos_habilitados":["qr","manual","facial"]
}
```

#### 5. `PUT /api/v1/mobile/me/perfil`
- Request JSON (compatible):
```json
{"telefono":"1133344455","direccion":"Calle 123","foto":"https://.../foto.jpg"}
```
- Para quitar foto via JSON tambien puede enviarse:
```json
{"foto":null}
```
- Request multipart/form-data (recomendado para subir imagen):
  - `telefono` (opcional)
  - `direccion` (opcional)
  - `foto` (opcional, URL manual)
  - `foto_file` (opcional, binario JPG/PNG/WEBP)
    - Compatibilidad: tambien se acepta archivo en campo `foto`.
  - `eliminar_foto` (opcional, `true/false`; si es `true` elimina foto actual)
- Restricciones:
  - No se permite enviar `foto_file` junto con `eliminar_foto=true`.
- Reglas de `foto_file`:
  - Tipo permitido: JPG, PNG, WEBP
  - Tamano maximo: `FOTO_MAX_BYTES` (default `5242880`, 5 MB)
- Response 200:
```json
{"id":12,"telefono":"1133344455","direccion":"Calle 123","foto":"https://.../foto.jpg","imagen_version":"1709294400"}
```

#### 6. `DELETE /api/v1/mobile/me/perfil/foto`
- Elimina la foto de perfil actual del empleado.
- Response 200:
```json
{"ok":true,"foto":null,"imagen_version":null}
```

#### 7. `GET /empleados/imagen/<dni>?v=<version>`
- Devuelve la imagen de perfil por DNI.
- Compatibilidad: se mantiene tambien `GET /media/empleados/foto/<dni>`.
- Cache: responde `ETag`. Si cliente envia `If-None-Match` sin cambios reales, responde `304 Not Modified`.
- El query param `v` se usa como cache busting cliente (recomendado: `v=<imagen_version>`).

#### 8. `PUT /api/v1/mobile/me/password`
- Request:
```json
{"password_actual":"secreta123","password_nueva":"nueva1234"}
```
- Response 200:
```json
{"ok":true}
```

---

### Fichadas

#### 9. `POST /api/v1/mobile/me/qr`
- Genera un QR de fichada.
- Request:
```json
{"accion":"auto","scope":"empresa","tipo_marca":"jornada","vigencia_segundos":2592000}
```
- `accion`: `ingreso`, `egreso` o `auto` (recomendado para QR unico de puerta).
- `scope`:
  - `empresa`: QR general para todos los empleados de la empresa (default)
  - `empleado`: QR exclusivo para el empleado autenticado
- `tipo_marca`: `jornada` (default), `desayuno`, `almuerzo`, `merienda`, `otro`
- `vigencia_segundos`: 30 a 315360000 (hasta 10 anios). Default: `2592000` (30 dias).
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

#### 10. `POST /api/v1/mobile/me/fichadas/scan`
- Endpoint principal. Backend detecta ingreso/egreso automaticamente.
- Valida geocerca GPS contra la ubicacion del QR (o sucursal asignada).
- Si fuera de rango, bloquea la fichada y registra evento de fraude.
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
- `lat` y `lon` son obligatorios.
- `qr_token` acepta JWT directo, `Bearer <jwt>`, URL con query `qr_token`/`token` o JSON con `qr_token`.
- `tipo_marca` es opcional; si el QR lo incluye, prevalece el del QR.
- Response 201 (ingreso):
```json
{"id":15,"marca_id":1201,"accion":"ingreso","tipo_marca":"almuerzo","estado":"ok","gps_ok":true,"distancia_m":12.4,"tolerancia_m":80.0,"alerta_fraude":false,"evento_id":null,"total_marcas_dia":1}
```
- Response 200 (egreso):
```json
{"id":15,"marca_id":1202,"accion":"egreso","tipo_marca":"almuerzo","estado":"ok","gps_ok":true,"distancia_m":9.8,"tolerancia_m":80.0,"alerta_fraude":false,"evento_id":null,"total_marcas_dia":2}
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
- Response 400 (QR invalido, vencido o de otro ambiente):
```json
{"error":"QR invalido o generado en otro ambiente. Genere un QR nuevo desde este sistema.","code":"qr_token_invalid_signature"}
```
- Codigos QR posibles: `qr_token_required`, `qr_token_malformed`, `qr_token_invalid`, `qr_token_invalid_signature`, `qr_token_expired`, `qr_token_wrong_type`, `qr_token_missing_empresa`, `qr_token_wrong_action`, `qr_not_registered`, `qr_inactive`, `qr_wrong_empresa`, `qr_wrong_empleado`.

#### 11. `POST /api/v1/mobile/me/fichadas/entrada` (deprecated)
- Para nuevas integraciones usar `POST /api/v1/mobile/me/fichadas/scan`.
- Request:
```json
{"fecha":"2026-02-14","metodo":"qr","qr_token":"<jwt_qr_ingreso>","hora_entrada":"08:03","lat":-34.6037,"lon":-58.3816,"foto":null,"observaciones":"Ingreso principal"}
```
- Response 201:
```json
{"id": 15, "estado":"ok"}
```

#### 12. `POST /api/v1/mobile/me/fichadas/salida` (deprecated)
- Para nuevas integraciones usar `POST /api/v1/mobile/me/fichadas/scan`.
- Request:
```json
{"fecha":"2026-02-14","metodo":"qr","qr_token":"<jwt_qr_egreso>","hora_salida":"16:02","lat":-34.6037,"lon":-58.3816}
```
- Response 200:
```json
{"id": 15, "estado":"ok"}
```

---

### Asistencias

#### 13. `GET /api/v1/mobile/me/horario-esperado?fecha=YYYY-MM-DD`
- Response 200:
```json
{
  "tiene_excepcion": false,
  "bloques":[{"entrada":"08:00","salida":"16:00"}],
  "tolerancia": 5
}
```
- Response 404: `{"error":"sin horario esperado"}`

#### 14. `GET /api/v1/mobile/me/asistencias?desde=&hasta=&page=&per=`
- Lista paginada de resumen diario de asistencias.
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

#### 15. `GET /api/v1/mobile/me/marcas?desde=&hasta=&page=&per=`
- Lista paginada de marcas atomicas (ingreso/egreso individuales).
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

---

### Estadisticas y Dashboard

#### 16. `GET /api/v1/mobile/me/estadisticas?desde=&hasta=`
- KPIs agregados del empleado para un rango de fechas.
- Defaults: `hasta` = hoy, `desde` = hoy - 29 dias.
- Restricciones: sin fechas futuras, `desde <= hasta`, maximo 366 dias.
- Response 200:
```json
{
  "periodo":{"desde":"2026-02-01","hasta":"2026-02-27","dias":27},
  "totales":{"registros":20,"ok":14,"tarde":3,"ausente":2,"salida_anticipada":1,"sin_estado":0},
  "kpis":{
    "puntualidad_pct":70.0,
    "ausentismo_pct":10.0,
    "cumplimiento_jornada_pct":88.9,
    "no_show_pct":50.0,
    "tasa_salida_anticipada_pct":5.0,
    "adherencia_pct":92.3,
    "horas_promedio":7.82,
    "horas_totales":125.1,
    "gps_incidencias":2,
    "dias_laborables":21,
    "dias_con_registro":19,
    "racha_ok":5
  },
  "jornadas":{"completas":16,"con_marca":18,"incompletas":2},
  "justificaciones":{"total":4,"pendientes":1,"aprobadas":2,"rechazadas":1,"tasa_aprobacion_pct":50.0,"tasa_justificacion_pct":100.0},
  "vacaciones":{"eventos":1,"dias":5},
  "ausencias":{"total":2,"sin_justificacion":1},
  "series":{
    "diaria":[{"fecha":"2026-02-01","registros":1,"ok":1,"tarde":0,"ausente":0,"salida_anticipada":0,"puntualidad_pct":100.0,"ausentismo_pct":0.0}],
    "semanal":[{"desde":"2026-02-03","hasta":"2026-02-07","registros":5,"ok":4,"tarde":1,"ausente":0,"salida_anticipada":0,"puntualidad_pct":80.0}]
  }
}
```
- Campos `kpis` nuevos vs 1.10.0:
  - `adherencia_pct`: % de dias laborables con al menos una marca
  - `horas_promedio`: horas promedio por jornada completa
  - `horas_totales`: horas trabajadas totales en el periodo
  - `gps_incidencias`: cantidad de marcas con GPS rechazado
  - `dias_laborables`: dias habiles (lun-vie) en el rango
  - `dias_con_registro`: dias con al menos una marca
  - `racha_ok`: dias consecutivos con estado ok (desde hoy hacia atras)
- Campo nuevo en `justificaciones`: `tasa_justificacion_pct` (aprobadas / ausentes * 100)
- Campo nuevo en `series`: `semanal` (resumen por semana ISO)
- Response 400: `{"error":"No se permiten fechas futuras en estadisticas."}`
- Response 500: `{"error":"No se pudieron obtener estadisticas."}`

#### 17. `GET /api/v1/mobile/me/dashboard?periodo=&desde=&hasta=`
- Dashboard consolidado para pantalla principal de la app.
- Query params:
  - `periodo`: `7d` | `30d` (default) | `mes_actual` | `90d`
  - `desde` + `hasta`: override custom (ISO date); ignora `periodo` si se envian.
- Restricciones: sin fechas futuras, maximo 366 dias.
- Response 200:
```json
{
  "periodo":{
    "desde":"2026-02-25",
    "hasta":"2026-03-26",
    "preset":"30d",
    "dias_habiles":21
  },
  "asistencia":{
    "totales":{"registros":20,"ok":14,"tarde":3,"ausente":2,"salida_anticipada":1,"sin_estado":0},
    "kpis":{
      "puntualidad_pct":70.0,
      "ausentismo_pct":10.0,
      "cumplimiento_jornada_pct":88.9,
      "no_show_pct":50.0,
      "tasa_salida_anticipada_pct":5.0,
      "adherencia_pct":92.3,
      "horas_promedio":7.82,
      "horas_totales":125.1,
      "gps_incidencias":2,
      "dias_laborables":21,
      "dias_con_registro":19,
      "racha_ok":5
    },
    "jornadas":{"completas":16,"con_marca":18,"incompletas":2},
    "justificaciones":{"total":4,"pendientes":1,"aprobadas":2,"rechazadas":1,"tasa_aprobacion_pct":50.0,"tasa_justificacion_pct":100.0},
    "vacaciones":{"eventos":1,"dias":5},
    "ausencias":{"total":2,"sin_justificacion":1},
    "series":{
      "diaria":[{"fecha":"2026-02-25","registros":1,"ok":1,"tarde":0,"ausente":0,"salida_anticipada":0,"puntualidad_pct":100.0,"ausentismo_pct":0.0}],
      "semanal":[{"desde":"2026-02-24","hasta":"2026-02-28","registros":5,"ok":4,"tarde":1,"ausente":0,"salida_anticipada":0,"puntualidad_pct":80.0}]
    }
  },
  "legajo":{
    "historico":{"total":12,"vigentes":10,"anulados":2},
    "periodo":{
      "total":3,
      "graves":1,
      "media":1,
      "leve":1
    },
    "por_tipo":[{"label":"Llamado de atencion","total":2,"pct":66.7}],
    "por_severidad":[{"severidad":"grave","total":1,"pct":33.3}],
    "recientes":[
      {
        "id":45,
        "empresa_id":3,
        "empleado_id":12,
        "tipo_id":3,
        "tipo_codigo":"llamado_atencion",
        "tipo_nombre":"Llamado de atencion",
        "fecha_evento":"2026-03-10",
        "fecha_desde":null,
        "fecha_hasta":null,
        "titulo":"Llegada tarde reiterada",
        "descripcion":"Tercer llamado en el mes",
        "estado":"vigente",
        "severidad":"grave",
        "justificacion_id":null,
        "created_at":"2026-03-10T09:00:00",
        "updated_at":"2026-03-10T09:00:00"
      }
    ]
  },
  "vacaciones_activas":[
    {"id":7,"empleado_id":12,"fecha_desde":"2026-04-01","fecha_hasta":"2026-04-15","observaciones":"Vacaciones anuales"}
  ],
  "francos_proximos":[
    {"id":3,"empleado_id":12,"fecha":"2026-03-28","motivo":"Franco compensatorio"}
  ],
  "horario_actual":{
    "id":5,
    "horario_id":2,
    "horario_nombre":"Turno mañana",
    "fecha_desde":"2026-01-01",
    "fecha_hasta":null,
    "dias":[{"dia_semana":1},{"dia_semana":2},{"dia_semana":3},{"dia_semana":4},{"dia_semana":5}]
  }
}
```
- Response 400: `{"error":"Rango de fechas invalido"}`
- Response 500: `{"error":"No se pudo calcular el dashboard."}`

---

### Justificaciones

#### 18. `GET /api/v1/mobile/me/justificaciones?desde=&hasta=&estado=&page=&per=`
- Lista paginada de justificaciones del empleado.
- `estado`: `pendiente` | `aprobada` | `rechazada` (opcional)
- Response 200:
```json
{
  "items":[
    {
      "id":10,
      "asistencia_id":1,
      "asistencia_fecha":"2026-02-14",
      "motivo":"Enfermedad con certificado medico",
      "archivo":"https://.../cert.pdf",
      "estado":"aprobada",
      "created_at":"2026-02-15T09:00:00"
    }
  ],
  "page":1,
  "per_page":20,
  "total":1
}
```

#### 19. `GET /api/v1/mobile/me/justificaciones/<id>`
- Response 200: objeto justificacion (mismo esquema que items arriba).
- Response 404: `{"error":"Justificacion no encontrada"}`

#### 20. `POST /api/v1/mobile/me/justificaciones`
- Request:
```json
{"asistencia_id":1,"motivo":"Enfermedad con certificado medico","archivo":"https://.../cert.pdf"}
```
- `asistencia_id`: opcional; si es null, la justificacion no tiene asistencia asociada.
- `archivo`: opcional; URL al documento adjunto.
- Estado inicial siempre: `pendiente`.
- Response 201: objeto justificacion creada.
- Response 400: `{"error":"motivo es requerido"}`

#### 21. `PUT /api/v1/mobile/me/justificaciones/<id>`
- Solo permite editar justificaciones en estado `pendiente`.
- Request:
```json
{"motivo":"Motivo actualizado","archivo":null}
```
- Response 200: objeto justificacion actualizada.
- Response 404: `{"error":"Justificacion no encontrada"}`
- Response 409: `{"error":"Solo se puede editar una justificacion pendiente (estado actual: 'aprobada')"}`

#### 22. `DELETE /api/v1/mobile/me/justificaciones/<id>`
- Solo permite retirar justificaciones en estado `pendiente`.
- Response 200: `{"ok":true}`
- Response 404: `{"error":"Justificacion no encontrada"}`
- Response 409: `{"error":"Solo se puede retirar una justificacion pendiente (estado actual: 'aprobada')"}`

---

### Vacaciones

> Nota: `/me/vacaciones*` se mantiene por compatibilidad, pero ahora opera sobre `vacaciones_movimientos`: crea solicitudes pendientes, permite editar solo pendientes y revierte aprobadas mediante ajuste. Para el flujo mobile con saldo LCT, dias pendientes y validacion de disponibilidad, usar `/vacaciones/resumen`, `/vacaciones/movimientos` y `/vacaciones/solicitar`.

#### 23. `GET /api/v1/mobile/me/vacaciones?desde=&hasta=&page=&per_page=`
- Lista paginada de periodos de vacaciones.
- Response 200:
```json
{
  "items":[
    {"id":7,"empleado_id":12,"fecha_desde":"2026-04-01","fecha_hasta":"2026-04-15","observaciones":"Vacaciones anuales"}
  ],
  "total":1,
  "page":1,
  "per_page":20
}
```

#### 24. `GET /api/v1/mobile/me/vacaciones/<id>`
- Response 200: objeto vacacion.
- Response 404: `{"error":"Vacacion no encontrada"}`

#### 25. `POST /api/v1/mobile/me/vacaciones`
- Request:
```json
{"fecha_desde":"2026-04-01","fecha_hasta":"2026-04-15","observaciones":"Vacaciones anuales"}
```
- `fecha_desde` y `fecha_hasta` son obligatorios.
- Response 201: objeto vacacion creada.
- Response 400: `{"error":"fecha_desde y fecha_hasta son requeridos"}`

#### 26. `PUT /api/v1/mobile/me/vacaciones/<id>`
- Request: mismo esquema que POST.
- Response 200: objeto vacacion actualizada.
- Response 404: `{"error":"Vacacion no encontrada"}`

#### 27. `DELETE /api/v1/mobile/me/vacaciones/<id>`
- Response 200: `{"ok":true}`
- Response 404: `{"error":"Vacacion no encontrada"}`

#### 27A. `GET /api/v1/mobile/vacaciones/resumen?anio=YYYY`
- Resumen de saldo de vacaciones del empleado autenticado para el anio solicitado.
- `anio`: opcional; default = anio actual del servidor.
- Validacion de `anio`: entero entre 2000 y 2100.

**Logica de calculo:**
- `dias_base`: dias por antiguedad al 31/12 segun LCT Art. 150 (14 / 21 / 28 / 35 dias).
- `dias_compensatorios`: dias extra acreditados por RRHH (ej. feriados trabajados, beneficios). Se cargan desde el panel web por empleado o por sector. Son adicionales al saldo base.
- `dias_ajustes`: correcciones manuales positivas o negativas.
- `dias_corresponden = dias_base + dias_compensatorios + dias_ajustes` ← total disponible del anio.
- `dias_tomados`: dias ya aprobados como tomados.
- `dias_pendientes`: solicitudes aun sin resolver.
- `dias_disponibles = dias_corresponden - dias_tomados`
- `dias_disponibles_con_pendientes = dias_disponibles - dias_pendientes` ← saldo real para solicitar.

**Ejemplo:** base=28, compensatorios=2 → corresponden=30. Toma 15 → disponibles=15.

**Regla proporcional (nuevos ingresos):** si `aplica_control_proporcional=true` (antiguedad < 1 anio al 31/12) y el empleado trabajo menos de la mitad de los dias habiles de su propio periodo de empleo, `dias_base` se recalcula como `dias_trabajados_anio // 20`.

- Response 200:
```json
{
  "ok":true,
  "anio":2026,
  "empleado":{"id":12,"dni":"30111222","nombre":"Ana Lopez"},
  "vacaciones":{
    "fecha_ingreso":"2020-08-10",
    "antiguedad_al_31_12":6,
    "dias_habiles_anio":261,
    "dias_habiles_anio_total":261,
    "dias_habiles_evaluados":261,
    "dias_trabajados_anio":220,
    "dias_trabajados_porcentaje":84.3,
    "umbral_proporcional_pct":50.0,
    "fecha_evaluacion_trabajo":"2026-12-31",
    "aplica_control_proporcional":false,
    "calculo_proporcional":false,
    "dias_base":21,
    "dias_compensatorios":2,
    "dias_ajustes":0,
    "dias_tomados":5,
    "dias_pendientes":3,
    "dias_corresponden":23,
    "dias_disponibles":18,
    "dias_disponibles_con_pendientes":15,
    "desglose_corresponde":[
      {"concepto":"Base LCT","dias":21},
      {"concepto":"Compensatorios","dias":2}
    ]
  }
}
```

**Referencia completa de campos `vacaciones`:**
| campo | descripcion |
|---|---|
| `dias_base` | Dias base LCT por antiguedad (Art. 150). |
| `dias_compensatorios` | Dias extra acreditados por RRHH (feriados trabajados, beneficios, etc.). |
| `dias_ajustes` | Correcciones manuales positivas o negativas. |
| `dias_corresponden` | Total = `dias_base + dias_compensatorios + dias_ajustes`. |
| `dias_tomados` | Dias aprobados ya consumidos. |
| `dias_pendientes` | Solicitudes aun sin resolver. |
| `dias_disponibles` | `dias_corresponden - dias_tomados`. |
| `dias_disponibles_con_pendientes` | Saldo real para solicitar (`dias_disponibles - dias_pendientes`). |
| `desglose_corresponde` | Array con cada concepto que compone `dias_corresponden`. Mostrar como "21 base + 2 comp. = 23 días". Solo incluye conceptos con valor > 0. |
| `dias_trabajados_anio` | Dias efectivamente trabajados en el periodo evaluado. |
| `dias_trabajados_porcentaje` | `dias_trabajados_anio / dias_habiles_anio * 100`. Para mostrar como "66 de 102 días hábiles (64.7%)". |
| `umbral_proporcional_pct` | Siempre `50.0`. El empleado necesita superar este porcentaje para no sufrir reduccion proporcional. |
| `aplica_control_proporcional` | `true` si tiene < 1 anio de antiguedad al 31/12 (unico caso en que puede activarse la regla). |
| `calculo_proporcional` | `true` si efectivamente se aplicó reduccion. Cuando es `true`, `dias_base` ya refleja el valor reducido. |
| `dias_habiles_anio_total` | Dias habiles del anio completo (261 aprox). Referencia. |
| `dias_habiles_evaluados` | Dias habiles desde la fecha de ingreso hasta `fecha_evaluacion_trabajo`. |
| `fecha_evaluacion_trabajo` | Hasta que fecha se evaluo asistencia (hoy si el anio es el actual). |
| `antiguedad_al_31_12` | Anios completos de antiguedad al 31/12 del anio consultado. |

**Flujo recomendado en Flutter:**
```
GET /vacaciones/resumen?anio=YYYY

1. KPIs: mostrar cards con dias_disponibles_con_pendientes, dias_pendientes,
         dias_tomados, dias_corresponden.

2. Desglose "Corresponde": iterar desglose_corresponde y mostrar cada concepto:
   "21 Base LCT  +  2 Compensatorios  =  23 días"

3. Dias trabajados: mostrar como
   "${dias_trabajados_anio} de ${dias_habiles_anio} días hábiles (${dias_trabajados_porcentaje}%)"
   Si aplica_control_proporcional=true, agregar nota sobre la regla proporcional.
   Si calculo_proporcional=true, mostrar aviso "Vacaciones calculadas proporcionalmente".

4. Movimientos rechazados: usar el campo afecta_saldo=false de /vacaciones/movimientos
   para mostrarlos visualmente atenuados o con tachado, dejando claro que no impactan el saldo.
```

- Response 400:
```json
{"ok":false,"error":"Anio invalido."}
```
- Response 500:
```json
{"ok":false,"error":"No se pudo calcular el resumen de vacaciones."}
```

#### 27B. `GET /api/v1/mobile/vacaciones/movimientos?anio=YYYY`
- Lista movimientos de vacaciones del empleado autenticado para un anio.
- `anio`: opcional; default = anio actual del servidor.
- `tipo`: `tomado` | `compensatorio` | `ajuste`.
- `estado`: `pendiente` | `aprobado` | `rechazado`.
- Response 200:
```json
{
  "ok":true,
  "anio":2026,
  "movimientos":[
    {
      "id":1,
      "tipo":"tomado",
      "dias":13,
      "fecha_desde":"2026-07-27",
      "fecha_hasta":"2026-08-08",
      "estado":"aprobado",
      "observacion":null,
      "es_reversion":false,
      "afecta_saldo":true
    },
    {
      "id":2,
      "tipo":"tomado",
      "dias":4,
      "fecha_desde":"2026-09-27",
      "fecha_hasta":"2026-09-30",
      "estado":"rechazado",
      "observacion":null,
      "es_reversion":false,
      "afecta_saldo":false
    },
    {
      "id":3,
      "tipo":"ajuste",
      "dias":13,
      "fecha_desde":null,
      "fecha_hasta":null,
      "estado":"aprobado",
      "observacion":"Reversion movimiento #1",
      "es_reversion":true,
      "afecta_saldo":false
    }
  ]
}
```

**Estructura de la respuesta:**
| campo raíz | descripcion |
|---|---|
| `ok` | `true` si la solicitud fue exitosa. |
| `anio` | Año consultado (entero). |
| `movimientos` | Array de objetos movimiento (puede ser vacío). |

**Campos de cada movimiento:**
| campo | descripcion |
|---|---|
| `id` | Identificador del movimiento. |
| `tipo` | `tomado` \| `compensatorio` \| `ajuste`. |
| `dias` | Cantidad de días del movimiento (entero o decimal). |
| `fecha_desde` | Fecha de inicio (`YYYY-MM-DD`) o `null` para ajustes sin rango. |
| `fecha_hasta` | Fecha de fin (`YYYY-MM-DD`) o `null` para ajustes sin rango. |
| `estado` | `pendiente` \| `aprobado` \| `rechazado`. |
| `observacion` | Texto libre o `null`. |
| `es_reversion` | `true` si el movimiento fue generado para revertir otro. Mostrar con estilo atenuado / tachado. |
| `afecta_saldo` | `false` para rechazados y reversiones. Cuando es `false` el movimiento se muestra a modo de historial pero **no impacta el saldo**. Usar para acompañar el número con un aviso tipo "Este movimiento no afecta tu saldo". |

**UX recomendada para movimientos:**
- `afecta_saldo=true` → estilo normal con chip de estado (verde/azul/naranja).
- `afecta_saldo=false, estado="rechazado"` → chip rojo "Rechazado", texto atenuado (opacity 0.6), agregar tooltip "No afecta tu saldo".
- `afecta_saldo=false, es_reversion=true` → fila gris/punteada, icono de reversión, sin chip de estado principal.
- Agregar padding inferior de al menos 80px a la lista de movimientos para que el FAB flotante no tape el último item.

- Response 400:
```json
{"ok":false,"error":"Anio invalido."}
```
- Response 500:
```json
{"ok":false,"error":"No se pudieron obtener los movimientos de vacaciones."}
```

#### 27C. `POST /api/v1/mobile/vacaciones/solicitar`
- Crea una solicitud de vacaciones como movimiento `tipo="tomado"` en estado `pendiente`.
- Valida saldo disponible usando `dias_disponibles_con_pendientes`.
- `fecha_desde` y `fecha_hasta` deben pertenecer al mismo anio.
- `dias_solicitados` se calcula como dias calendario inclusivos (`fecha_hasta - fecha_desde + 1`).
- Request:
```json
{"fecha_desde":"2026-01-10","fecha_hasta":"2026-01-14","observacion":"Solicitud vacaciones"}
```
- Response 201:
```json
{
  "ok":true,
  "message":"Solicitud de vacaciones registrada correctamente",
  "solicitud":{
    "id":33,
    "dias_solicitados":5,
    "estado":"pendiente",
    "fecha_desde":"2026-01-10",
    "fecha_hasta":"2026-01-14"
  }
}
```
- Response 400:
```json
{"ok":false,"error":"fecha_desde es requerida."}
```
- Response 409:
```json
{"ok":false,"error":"Saldo de vacaciones insuficiente."}
```
- Response 500:
```json
{"ok":false,"error":"No se pudo registrar la solicitud de vacaciones."}
```

---

### Adelantos

#### 27D. `GET /api/v1/mobile/me/adelantos/resumen`
- Resumen para la pantalla inicial de adelantos.
- Devuelve estado del mes actual, ultimo adelanto y contadores del historial.
- Response 200:
```json
{
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "ya_solicitado":true,
  "adelanto_mes_actual":{
    "id":81,
    "periodo":"2026-04",
    "periodo_year":2026,
    "periodo_month":4,
    "fecha_solicitud":"2026-04-17",
    "estado":"pendiente",
    "created_at":"2026-04-17T09:30:00",
    "resuelto_at":null,
    "resuelto_by_usuario":null
  },
  "ultimo_adelanto":{
    "id":71,
    "periodo":"2026-03",
    "periodo_year":2026,
    "periodo_month":3,
    "fecha_solicitud":"2026-03-14",
    "estado":"aprobado",
    "created_at":"2026-03-14T08:45:00",
    "resuelto_at":"2026-03-15T11:00:00",
    "resuelto_by_usuario":"rrhh"
  },
  "total_historial":2,
  "pendientes_total":1
}
```

#### 27E. `GET /api/v1/mobile/me/adelantos/estado`
- Devuelve el estado del adelanto para el mes calendario actual del servidor.
- `adelanto` usa el mismo esquema que los endpoints de historial, detalle y alta.
- Response 200:
```json
{
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "ya_solicitado":true,
  "adelanto":{
    "id":81,
    "periodo":"2026-04",
    "periodo_year":2026,
    "periodo_month":4,
    "fecha_solicitud":"2026-04-17",
    "estado":"pendiente",
    "created_at":"2026-04-17T09:30:00",
    "resuelto_at":null,
    "resuelto_by_usuario":null
  }
}
```
- Si todavia no hubo solicitud en el mes: `ya_solicitado=false` y `adelanto=null`.

#### 27F. `GET /api/v1/mobile/me/adelantos?page=&per_page=&estado=`
- Lista paginada del historial de adelantos del empleado autenticado.
- `estado`: `pendiente` | `aprobado` | `rechazado` | `cancelado` (opcional)
- Response 200:
```json
{
  "items":[
    {
      "id":81,
      "periodo":"2026-04",
      "periodo_year":2026,
      "periodo_month":4,
      "fecha_solicitud":"2026-04-17",
      "estado":"aprobado",
      "created_at":"2026-04-17T09:30:00",
      "resuelto_at":"2026-04-18T11:10:00",
      "resuelto_by_usuario":"rrhh"
    }
  ],
  "total":1,
  "page":1,
  "per_page":20
}
```
- Response 400: `{"error":"estado invalido. Valores: pendiente, aprobado, rechazado, cancelado"}`

#### 27G. `GET /api/v1/mobile/me/adelantos/<id>`
- Devuelve el detalle de un adelanto propio.
- Response 200:
```json
{
  "id":81,
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "fecha_solicitud":"2026-04-17",
  "estado":"aprobado",
  "created_at":"2026-04-17T09:30:00",
  "resuelto_at":"2026-04-18T11:10:00",
  "resuelto_by_usuario":"rrhh"
}
```
- Response 404: `{"error":"Adelanto no encontrado"}`

#### 27H. `POST /api/v1/mobile/me/adelantos`
- No requiere body.
- Crea una solicitud de adelanto para el mes calendario actual.
- Estado inicial siempre: `pendiente`.
- Response 201:
```json
{
  "id":81,
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "fecha_solicitud":"2026-04-17",
  "estado":"pendiente",
  "created_at":"2026-04-17T09:30:00",
  "resuelto_at":null,
  "resuelto_by_usuario":null
}
```
- Response 409: `{"error":"Ya solicitaste un adelanto en este mes."}`

---

### Pedidos de mercaderia

#### Esquema `PedidoMercaderiaItem`
- Campos principales:
  - `id`
  - `periodo`, `periodo_year`, `periodo_month`
  - `fecha_pedido`
  - `estado`: `pendiente` | `aprobado` | `rechazado` | `cancelado`
  - `cantidad_items`
  - `total_bultos`
  - `motivo_rechazo`
  - `created_at`
  - `resuelto_at`
  - `resuelto_by_usuario`
  - `items[]`
- Cada item dentro de `items[]` expone:
  - `id`
  - `articulo_id`
  - `codigo_articulo`
  - `descripcion`
  - `unidades_por_bulto`
  - `cantidad_bultos`

#### Flujo recomendado para Flutter
1. Llamar `GET /api/v1/mobile/me/pedidos-mercaderia/resumen` al abrir la pantalla.
2. Si `ya_solicitado=false`, cargar el catalogo con `GET /api/v1/mobile/me/pedidos-mercaderia/articulos`.
3. Crear con `POST /api/v1/mobile/me/pedidos-mercaderia`.
4. Si el pedido sigue `pendiente`, actualizar con `PUT /api/v1/mobile/me/pedidos-mercaderia/<id>` o cancelar con `DELETE /api/v1/mobile/me/pedidos-mercaderia/<id>`.
5. Para historial aprobado, usar `GET /api/v1/mobile/me/pedidos-mercaderia?estado=aprobado`.

#### 27I. `GET /api/v1/mobile/me/pedidos-mercaderia/resumen`
- Resumen para la pantalla inicial de pedidos de mercaderia.
- Devuelve estado del mes actual, ultimo pedido, ultimo aprobado y contadores.
- Response 200:
```json
{
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "ya_solicitado":true,
  "pedido_mes_actual":{
    "id":91,
    "periodo":"2026-04",
    "periodo_year":2026,
    "periodo_month":4,
    "fecha_pedido":"2026-04-18",
    "estado":"pendiente",
    "cantidad_items":2,
    "total_bultos":3,
    "motivo_rechazo":null,
    "created_at":"2026-04-18T09:30:00",
    "resuelto_at":null,
    "resuelto_by_usuario":null,
    "items":[
      {
        "id":1,
        "articulo_id":5,
        "codigo_articulo":"A1",
        "descripcion":"Gaseosa",
        "unidades_por_bulto":8,
        "cantidad_bultos":2
      }
    ]
  },
  "ultimo_pedido":{
    "id":91,
    "periodo":"2026-04",
    "periodo_year":2026,
    "periodo_month":4,
    "fecha_pedido":"2026-04-18",
    "estado":"pendiente",
    "cantidad_items":2,
    "total_bultos":3,
    "motivo_rechazo":null,
    "created_at":"2026-04-18T09:30:00",
    "resuelto_at":null,
    "resuelto_by_usuario":null,
    "items":[]
  },
  "ultimo_pedido_aprobado":{
    "id":81,
    "periodo":"2026-03",
    "periodo_year":2026,
    "periodo_month":3,
    "fecha_pedido":"2026-03-14",
    "estado":"aprobado",
    "cantidad_items":1,
    "total_bultos":2,
    "motivo_rechazo":null,
    "created_at":"2026-03-14T08:45:00",
    "resuelto_at":"2026-03-15T11:00:00",
    "resuelto_by_usuario":"rrhh",
    "items":[]
  },
  "total_historial":2,
  "historial_aprobados_total":1,
  "pendientes_total":1
}
```

#### 27J. `GET /api/v1/mobile/me/pedidos-mercaderia/estado`
- Devuelve el estado del pedido del mes calendario actual del servidor.
- `pedido` usa el mismo esquema que detalle, alta y actualizacion.
- Response 200:
```json
{
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "ya_solicitado":true,
  "pedido":{
    "id":91,
    "periodo":"2026-04",
    "periodo_year":2026,
    "periodo_month":4,
    "fecha_pedido":"2026-04-18",
    "estado":"pendiente",
    "cantidad_items":2,
    "total_bultos":3,
    "motivo_rechazo":null,
    "created_at":"2026-04-18T09:30:00",
    "resuelto_at":null,
    "resuelto_by_usuario":null,
    "items":[
      {
        "id":1,
        "articulo_id":5,
        "codigo_articulo":"A1",
        "descripcion":"Gaseosa",
        "unidades_por_bulto":8,
        "cantidad_bultos":2
      }
    ]
  }
}
```
- Si todavia no hubo pedido en el mes: `ya_solicitado=false` y `pedido=null`.

#### 27K. `GET /api/v1/mobile/me/pedidos-mercaderia/articulos?q=&page=&per_page=`
- Catalogo paginado de articulos habilitados para pedido.
- `q` es opcional y busca por codigo, descripcion, marca, familia o sabor.
- Solo expone articulos importados desde CSV con:
  - `Activo = SI`
  - `Anulado = NO`
  - `Usado en dispositivo movil = SI`
  - `TIPO DE PRODUCTO = MERCADERIA`
- Response 200:
```json
{
  "items":[
    {
      "id":5,
      "codigo_articulo":"A1",
      "descripcion":"Gaseosa",
      "unidades_por_bulto":8,
      "bultos_por_pallet":72,
      "marca":"Marca",
      "familia":"Familia",
      "sabor":"Cola",
      "division":"Bebidas"
    }
  ],
  "total":1,
  "page":1,
  "per_page":20
}
```

#### 27L. `GET /api/v1/mobile/me/pedidos-mercaderia?page=&per_page=&estado=`
- Lista paginada del historial de pedidos del empleado autenticado.
- `estado`: `pendiente` | `aprobado` | `rechazado` | `cancelado` (opcional)
- Para historial de aprobados usar `estado=aprobado`.
- Response 200:
```json
{
  "items":[
    {
      "id":91,
      "periodo":"2026-04",
      "periodo_year":2026,
      "periodo_month":4,
      "fecha_pedido":"2026-04-18",
      "estado":"pendiente",
      "cantidad_items":2,
      "total_bultos":3,
      "motivo_rechazo":null,
      "created_at":"2026-04-18T09:30:00",
      "resuelto_at":null,
      "resuelto_by_usuario":null,
      "items":[
        {
          "id":1,
          "articulo_id":5,
          "codigo_articulo":"A1",
          "descripcion":"Gaseosa",
          "unidades_por_bulto":8,
          "cantidad_bultos":2
        }
      ]
    }
  ],
  "total":1,
  "page":1,
  "per_page":20
}
```
- Response 400: `{"error":"estado invalido. Valores: pendiente, aprobado, rechazado, cancelado"}`

#### 27M. `GET /api/v1/mobile/me/pedidos-mercaderia/<id>`
- Devuelve el detalle de un pedido propio.
- Response 200:
```json
{
  "id":91,
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "fecha_pedido":"2026-04-18",
  "estado":"aprobado",
  "cantidad_items":2,
  "total_bultos":3,
  "motivo_rechazo":null,
  "created_at":"2026-04-18T09:30:00",
  "resuelto_at":"2026-04-19T11:10:00",
  "resuelto_by_usuario":"rrhh",
  "items":[
    {
      "id":1,
      "articulo_id":5,
      "codigo_articulo":"A1",
      "descripcion":"Gaseosa",
      "unidades_por_bulto":8,
      "cantidad_bultos":2
    }
  ]
}
```
- Response 404: `{"error":"Pedido no encontrado"}`

#### 27N. `POST /api/v1/mobile/me/pedidos-mercaderia`
- Crea el pedido del mes actual.
- Solo se permite un pedido por empleado por mes.
- Validaciones:
  - `items` es obligatorio
  - no se permite repetir el mismo `articulo_id` dentro del mismo pedido
  - `cantidad_bultos` debe ser entero mayor a cero
  - el articulo debe existir y estar habilitado para pedido
- Request body:
```json
{
  "items":[
    {"articulo_id":5, "cantidad_bultos":2},
    {"articulo_id":6, "cantidad_bultos":1}
  ]
}
```
- Response 201:
```json
{
  "id":91,
  "periodo":"2026-04",
  "periodo_year":2026,
  "periodo_month":4,
  "fecha_pedido":"2026-04-18",
  "estado":"pendiente",
  "cantidad_items":2,
  "total_bultos":3,
  "motivo_rechazo":null,
  "created_at":"2026-04-18T09:30:00",
  "resuelto_at":null,
  "resuelto_by_usuario":null,
  "items":[
    {
      "id":1,
      "articulo_id":5,
      "codigo_articulo":"A1",
      "descripcion":"Gaseosa",
      "unidades_por_bulto":8,
      "cantidad_bultos":2
    }
  ]
}
```
- Response 400: `{"error":"Debe enviar al menos un articulo."}`
- Response 409: `{"error":"Ya registraste un pedido de mercaderia en este mes."}`

#### 27O. `PUT /api/v1/mobile/me/pedidos-mercaderia/<id>`
- Reemplaza los items de un pedido propio.
- Solo disponible en estado `pendiente`.
- Request body:
```json
{
  "items":[
    {"articulo_id":5, "cantidad_bultos":4}
  ]
}
```
- Response 200: mismo esquema que `GET /api/v1/mobile/me/pedidos-mercaderia/<id>`
- Response 400: `{"error":"No se puede editar un pedido en estado 'aprobado'."}`
- Response 404: `{"error":"Pedido no encontrado"}`

#### 27P. `DELETE /api/v1/mobile/me/pedidos-mercaderia/<id>`
- Cancela el pedido del mes.
- No elimina fisicamente el registro.
- Solo disponible en estado `pendiente`.
- Response 200: mismo esquema que `GET /api/v1/mobile/me/pedidos-mercaderia/<id>`, con `estado="cancelado"`.
- Response 400: `{"error":"No se puede cancelar un pedido en estado 'aprobado'."}`
- Response 404: `{"error":"Pedido no encontrado"}`

---

### Horarios

#### 28. `GET /api/v1/mobile/me/horarios-asignaciones`
- Lista historial completo de asignaciones de horario del empleado.
- Response 200 (array):
```json
[
  {
    "id":5,
    "horario_id":2,
    "horario_nombre":"Turno mañana",
    "fecha_desde":"2026-01-01",
    "fecha_hasta":null
  }
]
```

#### 29. `GET /api/v1/mobile/me/horarios-asignaciones/actual`
- Asignacion de horario vigente a la fecha actual con detalle de dias.
- Response 200 (con horario asignado):
```json
{
  "asignacion":{"id":5,"horario_id":2,"horario_nombre":"Turno mañana","fecha_desde":"2026-01-01","fecha_hasta":null},
  "dias":[{"dia_semana":1},{"dia_semana":2},{"dia_semana":3},{"dia_semana":4},{"dia_semana":5}]
}
```
- `dia_semana`: 1=Lunes ... 7=Domingo (ISO week day)
- Response 200 (sin horario asignado):
```json
{"asignacion":null,"dias":[]}
```

---

### Francos

#### 30. `GET /api/v1/mobile/me/francos?desde=&hasta=&page=&per_page=`
- Lista paginada de francos (dias libres) del empleado.
- Response 200:
```json
{
  "items":[
    {"id":3,"empleado_id":12,"fecha":"2026-03-28","motivo":"Franco compensatorio"}
  ],
  "total":1,
  "page":1,
  "per_page":20
}
```

#### 31. `GET /api/v1/mobile/me/francos/<id>`
- Response 200: objeto franco.
- Response 404: `{"error":"Franco no encontrado"}`

---

### Legajo

#### 32. `GET /api/v1/mobile/me/legajo/resumen?periodo=&desde=&hasta=`
- Resumen del legajo del empleado autenticado.
- `periodo`: `7d` | `30d` | `90d` | `mes_actual` | `anio_actual` | `custom`. Default: `anio_actual`.
- `desde` / `hasta`: fechas ISO `YYYY-MM-DD`. Si se informan, fuerzan `periodo=custom`.
- Response 200:
```json
{
  "ok": true,
  "periodo": {
    "desde": "2026-01-01",
    "hasta": "2026-05-16",
    "preset": "anio_actual"
  },
  "resumen": {
    "historico": {"total": 8, "vigentes": 7, "anulados": 1},
    "periodo": {"total": 3, "graves": 0, "media": 1, "leve": 2, "sin_severidad": 0},
    "por_tipo": [{"label": "Llamado de atencion", "total": 2, "pct": 66.7}],
    "por_severidad": [{"severidad": "leve", "total": 2, "pct": 66.7}],
    "recientes": []
  }
}
```
- Response 400: `{"ok":false,"error":"El rango de fechas es invalido (desde > hasta)."}`

#### 33. `GET /api/v1/mobile/me/legajo/tipos-evento`
- Tipos de evento activos para renderizar filtros/formularios mobile.
- Response 200:
```json
{
  "ok": true,
  "items": [
    {
      "id": 3,
      "codigo": "llamado_atencion",
      "nombre": "Llamado de atencion",
      "requiere_rango_fechas": false,
      "permite_adjuntos": true,
      "activo": true
    }
  ],
  "total": 1
}
```

#### 34. `GET /api/v1/mobile/me/legajo/eventos?tipo_id=&estado=&severidad=&desde=&hasta=&q=&page=&per_page=`
- Lista paginada de eventos del legajo del empleado.
- `estado`: `vigente` | `anulado` | `all` (opcional)
- `severidad`: `leve` | `media` | `grave` | `all` (opcional)
- `desde` / `hasta`: filtran por `fecha_evento`.
- `q`: busca por titulo, descripcion o datos del empleado.
- Response 200:
```json
{
  "ok": true,
  "items":[
    {
      "id":45,
      "empresa_id": 3,
      "empleado_id": 12,
      "tipo_id":3,
      "tipo_codigo":"llamado_atencion",
      "tipo_nombre":"Llamado de atencion",
      "fecha_evento":"2026-03-10",
      "fecha_desde":null,
      "fecha_hasta":null,
      "titulo":"Llegada tarde reiterada",
      "descripcion":"Tercer llamado en el mes",
      "estado":"vigente",
      "severidad":"grave",
      "justificacion_id": null,
      "created_at": "2026-03-10T09:00:00",
      "updated_at": "2026-03-10T09:00:00"
    }
  ],
  "total":1,
  "page":1,
  "per_page":20,
  "pagination": {"page":1, "per_page":20, "total":1, "has_more":false}
}
```
- Response 400: `{"ok":false,"error":"estado debe ser 'vigente' o 'anulado'"}`

#### 35. `GET /api/v1/mobile/me/legajo/eventos/<id>`
- Detalle de un evento del legajo. No incluye documentacion adjunta.
- Response 200:
```json
{
  "ok": true,
  "id": 45,
  "empresa_id": 3,
  "empleado_id": 12,
  "tipo_id": 3,
  "tipo_codigo": "llamado_atencion",
  "tipo_nombre": "Llamado de atencion",
  "fecha_evento": "2026-03-10",
  "fecha_desde": null,
  "fecha_hasta": null,
  "titulo": "Llegada tarde reiterada",
  "descripcion": "Tercer llamado en el mes",
  "estado": "vigente",
  "severidad": "grave",
  "justificacion_id": null,
  "created_at": "2026-03-10T09:00:00",
  "updated_at": "2026-03-10T09:00:00"
}
```
- Response 404: `{"ok":false,"error":"Evento no encontrado"}`

#### 36. `GET /api/v1/mobile/me/legajo/adjuntos/<id>` — BLOQUEADO
- Acceso a documentacion deshabilitado para empleados.
- Response 403: `{"ok":false,"error":"No autorizado"}`

#### 36A. `GET /api/v1/mobile/me/legajo/historial-por-tipo`
- Devuelve todos los tipos de evento activos con la cantidad total de eventos y eventos vigentes del empleado autenticado.
- Util para mostrar un resumen tipo tarjeta por categoria en la pantalla de legajo.
- Incluye tipos con `total: 0` para que Flutter pueda pintar todas las categorias.
- Ordenado por `total` descendente, luego nombre.
- Response 200:
```json
{
  "ok": true,
  "total_tipos": 4,
  "items": [
    {
      "tipo_id": 3,
      "codigo": "llamado_atencion",
      "nombre": "Llamado de atencion",
      "total": 5,
      "vigentes": 4,
      "ultima_fecha": "2026-03-10"
    },
    {
      "tipo_id": 1,
      "codigo": "felicitacion",
      "nombre": "Felicitacion",
      "total": 2,
      "vigentes": 2,
      "ultima_fecha": "2025-08-01"
    },
    {
      "tipo_id": 5,
      "codigo": "capacitacion",
      "nombre": "Capacitacion",
      "total": 0,
      "vigentes": 0,
      "ultima_fecha": null
    }
  ]
}
```
- Campos:
  - `total`: eventos del empleado en este tipo (vigentes + anulados)
  - `vigentes`: solo eventos en estado `vigente`
  - `ultima_fecha`: fecha del evento mas reciente (`null` si no tiene ninguno)
- Response 500: `{"ok":false,"error":"No se pudo obtener el historial por tipo."}`

---

### KPIs Sectoriales

#### 37. `GET /api/v1/mobile/me/kpis-sector?anio=YYYY`
- KPIs del sector del empleado autenticado para el año solicitado.
- `anio`: año a consultar (opcional, default = año actual del servidor).
- Para cada KPI muestra resultado acumulado vs objetivo anual del sector, con semaforo y recomendacion.
- Fuente de datos: resultados cargados por CSV desde el panel web. Los codigos KPI se interpretan dentro del sector actual del empleado.
- Regla de refresco de datos: si una importacion web contiene filas del mes actual del servidor, backend reemplaza ese mes solo para los empleados incluidos en el CSV antes de insertar los nuevos datos. Los meses historicos no se borran masivamente; se insertan/actualizan registros coincidentes.
- Response 200:
```json
{
  "anio": 2026,
  "sector": {
    "id": 3,
    "nombre": "Entrega"
  },
  "kpis": [
    {
      "kpi_id": 1,
      "codigo": "BULTOS_ENT",
      "nombre": "Bultos entregados",
      "unidad": "bultos",
      "tipo_acumulacion": "suma",
      "mayor_es_mejor": true,
      "condicion": "gte",
      "condicion_simbolo": "≥",
      "objetivo_anual": 1200.0,
      "valor_min": null,
      "valor_max": null,
      "resultado_acumulado": 450.0,
      "progreso_pct": 37.5,
      "progreso_esperado_pct": 30.0,
      "semaforo": "verde",
      "recomendacion": "En camino al objetivo anual."
    },
    {
      "kpi_id": 2,
      "codigo": "DISPERSION_KM",
      "nombre": "Dispersion de recorrido",
      "unidad": "km",
      "tipo_acumulacion": "promedio",
      "mayor_es_mejor": false,
      "condicion": "between",
      "condicion_simbolo": "entre",
      "objetivo_anual": 0.0,
      "valor_min": 8.0,
      "valor_max": 12.0,
      "resultado_acumulado": 10.3,
      "progreso_pct": 0.0,
      "progreso_esperado_pct": 100.0,
      "semaforo": "verde",
      "recomendacion": "Dentro del rango objetivo (8.0 – 12.0)."
    }
  ]
}
```
- Campos del KPI:
  - `tipo_acumulacion`: `suma` | `promedio` | `ultimo`
    - `suma`: `resultado_acumulado` = suma de todos los registros diarios del año. Ideal para conteos (bultos, entregas).
    - `promedio`: `resultado_acumulado` = promedio de todos los registros del año. Ideal para tasas o porcentajes (satisfaccion, calidad).
    - `ultimo`: `resultado_acumulado` = el valor mas reciente cargado en el año (por fecha). Ideal para indicadores tipo snapshot que se reemplazan al cambiar (NPS, stock, tasas que no se promedian).
  - `mayor_es_mejor`: `true` si mayor valor es mejor resultado
  - `condicion`: `gte` | `lte` | `eq` | `between`
  - `condicion_simbolo`: `≥` | `≤` | `=` | `entre`
  - `objetivo_anual`: objetivo simple del sector (0 si condicion es `between` o no configurado)
  - `valor_min` / `valor_max`: limites del rango (`null` salvo condicion `between`)
  - `resultado_acumulado`: valor acumulado del empleado en el año segun `tipo_acumulacion` (ver arriba)
  - `progreso_pct`: porcentaje del objetivo cubierto (`resultado / objetivo * 100`); 0 para `between`
  - `progreso_esperado_pct`: porcentaje del año transcurrido (ritmo lineal); 100 para `promedio`/`ultimo`/`between`
  - `semaforo`: `verde` | `amarillo` | `rojo` | `gris`
    - `gris`: sin objetivo definido
    - Condicion `gte`: verde ≥90% ritmo, amarillo 70-90%, rojo <70%
    - Condicion `lte`: verde ≤110% del limite, amarillo ≤130%, rojo >130%
    - Condicion `eq`: verde ±10%, amarillo ±25%, rojo fuera
    - Condicion `between`: verde dentro del rango, amarillo ≤10% del margen exterior, rojo fuera
  - `recomendacion`: texto corto para mostrar al empleado
- Si el empleado no tiene sector asignado, `sector.id` es `null` y `kpis` es `[]`.
- Response 400: `{"error":"Ano invalido."}`
- Response 500: `{"error":"No se pudieron obtener los KPIs."}`

#### 37A. `GET /api/v1/mobile/me/kpis-sector/resumen?anio=YYYY&limit_meses=N&include_series=true&series_dias=60`
- Vista ampliada de KPIs del sector del empleado autenticado.
- Mantiene la vista actual dentro de `vista_actual.kpis` y agrega:
  - `ultimo_cargado`: ultimo resultado de KPI cargado para el empleado en el anio consultado.
  - `meses_cerrados`: KPIs agrupados por meses calendario cerrados.
  - `series_diaria` *(opcional)*: serie diaria de resultados por KPI con acumulados y semaforos por punto.
- Usa la misma fuente y regla de refresco de datos que `GET /me/kpis-sector`.
- `anio`: anio a consultar (opcional, default = anio actual del servidor).
- `limit_meses`: cantidad de meses cerrados a devolver, entero entre 1 y 12 (opcional, default = 6).
- `include_series`: `true` o `1` para incluir `series_diaria` en la respuesta (opcional, default omitido → no se incluye).
- `series_dias`: cantidad de dias de historia a mostrar en `series_diaria`, entero entre 1 y 365 (opcional, default = 60). Solo aplica si `include_series=true`.
- Un mes cerrado es un mes calendario completo anterior al mes actual del servidor. Ejemplo: si hoy es 2026-05-28, el ultimo mes cerrado es 2026-04.
- `meses_cerrados` se devuelve de mas reciente a mas antiguo.
- Response 200 (sin `include_series`):
```json
{
  "anio": 2026,
  "sector": {
    "id": 3,
    "nombre": "Entrega"
  },
  "vista_actual": {
    "kpis": [
      {
        "kpi_id": 1,
        "codigo": "BULTOS_ENT",
        "nombre": "Bultos entregados",
        "unidad": "bultos",
        "tipo_acumulacion": "suma",
        "mayor_es_mejor": true,
        "condicion": "gte",
        "condicion_simbolo": ">=",
        "objetivo_anual": 1200.0,
        "valor_min": null,
        "valor_max": null,
        "resultado_acumulado": 450.0,
        "progreso_pct": 37.5,
        "progreso_esperado_pct": 30.0,
        "semaforo": "verde",
        "recomendacion": "En camino al objetivo anual."
      }
    ]
  },
  "ultimo_cargado": {
    "kpi_id": 1,
    "codigo": "BULTOS_ENT",
    "nombre": "Bultos entregados",
    "unidad": "bultos",
    "tipo_acumulacion": "suma",
    "mayor_es_mejor": true,
    "condicion": "gte",
    "condicion_simbolo": ">=",
    "objetivo_anual": 1200.0,
    "objetivo_periodo": 3.2877,
    "valor_min": null,
    "valor_max": null,
    "resultado": 38.0,
    "valor": 38.0,
    "progreso_pct": 1155.8,
    "semaforo": "verde",
    "recomendacion": "En camino al objetivo anual.",
    "fecha_resultado": "2026-04-30",
    "cargado_at": "2026-05-01T08:15:00"
  },
  "meses_cerrados": [
    {
      "periodo": "2026-04",
      "periodo_year": 2026,
      "periodo_month": 4,
      "mes_nombre": "Abril",
      "desde": "2026-04-01",
      "hasta": "2026-04-30",
      "cerrado": true,
      "resumen": {
        "total": 1,
        "verde": 1,
        "amarillo": 0,
        "rojo": 0,
        "gris": 0
      },
      "kpis": [
        {
          "kpi_id": 1,
          "codigo": "BULTOS_ENT",
          "nombre": "Bultos entregados",
          "unidad": "bultos",
          "tipo_acumulacion": "suma",
          "mayor_es_mejor": true,
          "condicion": "gte",
          "condicion_simbolo": ">=",
          "objetivo_anual": 1200.0,
          "objetivo_mes": 98.6301,
          "valor_min": null,
          "valor_max": null,
          "resultado_mes": 120.0,
          "progreso_pct": 121.7,
          "semaforo": "verde",
          "recomendacion": "En camino al objetivo anual.",
          "registros": 20,
          "fecha_ultimo_resultado": "2026-04-30"
        }
      ]
    }
  ],
  "meta": {
    "limit_meses": 6,
    "include_series": false,
    "series_dias": null
  }
}
```
- Response 200 con `include_series=true` — agrega el campo `series_diaria` y actualiza `meta`:
```json
{
  "meta": {
    "limit_meses": 6,
    "include_series": true,
    "series_dias": 60
  },
  "series_diaria": [
    {
      "kpi_id": 1,
      "codigo": "BULTOS_ENT",
      "nombre": "Bultos entregados",
      "unidad": "bultos",
      "tipo_acumulacion": "suma",
      "condicion": "gte",
      "condicion_simbolo": "≥",
      "objetivo_anual": 1200.0,
      "valor_min": null,
      "valor_max": null,
      "periodo_desde": "2026-03-29",
      "periodo_hasta": "2026-05-28",
      "puntos": [
        {
          "fecha": "2026-05-27",
          "resultado_dia": 38.0,
          "objetivo_dia": 3.2877,
          "resultado_acumulado_a_fecha": 420.0,
          "objetivo_acumulado_a_fecha": 405.0,
          "progreso_dia_pct": 115.6,
          "progreso_acumulado_pct": 103.7,
          "semaforo_dia": "verde",
          "semaforo_acumulado": "verde"
        }
      ]
    }
  ]
}
```

##### Reglas de `series_diaria`

- Solo se incluye si `include_series=true`. Si no se pide, la clave `series_diaria` no existe en el payload (Flutter debe ignorar campos desconocidos).
- `puntos` solo contiene fechas con resultado real cargado. Los dias sin dato no se incluyen (no se rellena con 0).
- `periodo_desde` / `periodo_hasta`: ventana de display = `[hoy - series_dias + 1, hoy]`, acotada al inicio del anio.
- Los `resultado_acumulado_a_fecha` se calculan desde el inicio del anio, no solo desde `periodo_desde`. Esto garantiza que el acumulado sea correcto aunque el primer punto visible no sea el primero del anio.
- `objetivo_dia` y `objetivo_acumulado_a_fecha` por tipo:
  | tipo_acumulacion | condicion | objetivo_dia | objetivo_acumulado_a_fecha |
  |---|---|---|---|
  | `suma` | cualquiera menos `between` | `objetivo_anual / dias_en_año` | `objetivo_anual × (dia_del_año / total_dias)` |
  | `promedio` | cualquiera menos `between` | `objetivo_anual` | `objetivo_anual` |
  | `ultimo` | cualquiera menos `between` | `objetivo_anual` | `objetivo_anual` |
  | cualquiera | `between` | `null` | `null` (usar `valor_min`/`valor_max`) |
- Para `ultimo`: cada `resultado_dia` es el valor del registro de esa fecha; `resultado_acumulado_a_fecha` es el ultimo valor cargado hasta esa fecha (equivale al valor del punto mas reciente en la ventana, no un promedio ni una suma).
- Para `ultimo` en `meses_cerrados`: `resultado_mes` es el valor del ultimo registro del mes (el mas reciente por fecha dentro del mes), no el promedio ni la suma.
- `semaforo_dia` y `semaforo_acumulado`: mismas reglas que el semaforo de `vista_actual` (verde/amarillo/rojo/gris).
- `puntos: []` si el KPI no tiene resultados en el anio (el KPI igual aparece en la lista con su definicion).

- `ultimo_cargado` es `null` si el empleado no tiene resultados cargados en el anio.
- `fecha_resultado`: fecha operativa del KPI informada en el CSV.
- `cargado_at`: fecha tecnica de insercion o ultima actualizacion en backend.
- Para meses sin datos en un KPI, `resultado_mes` es `null`, `registros` es `0` y `semaforo` es `"gris"`.
- Si el empleado no tiene sector asignado, `sector.id` es `null`, `vista_actual.kpis` es `[]`, `ultimo_cargado` es `null`, `meses_cerrados` es `[]` y `series_diaria` es `[]`.
- Response 400:
  - `{"error":"Ano invalido."}`
  - `{"error":"limit_meses invalido. Use un entero entre 1 y 12."}`
  - `{"error":"series_dias invalido. Use un entero entre 1 y 365."}`
- Response 500: `{"error":"No se pudieron obtener las vistas de KPIs."}`

#### 37B. `GET /api/v1/mobile/me/kpis-sector/dia?fecha=YYYY-MM-DD`
- Snapshot de todos los KPIs activos del sector del empleado autenticado para una fecha concreta.
- `fecha`: requerido, formato `YYYY-MM-DD`. No puede ser futura.
- Siempre devuelve una fila por KPI, haya o no resultado cargado para ese día exacto.
- El acumulado se calcula desde el 1 de enero del año de la fecha consultada.
- Response 200:
```json
{
  "fecha": "2026-05-27",
  "sector": {
    "id": 3,
    "nombre": "Entrega"
  },
  "kpis": [
    {
      "kpi_id": 1,
      "codigo": "BULTOS_ENT",
      "nombre": "Bultos entregados",
      "unidad": "bultos",
      "tipo_acumulacion": "suma",
      "mayor_es_mejor": true,
      "condicion": "gte",
      "condicion_simbolo": "≥",
      "objetivo_anual": 1200.0,
      "valor_min": null,
      "valor_max": null,
      "tiene_resultado": true,
      "resultado_dia": 38.0,
      "objetivo_dia": 3.2877,
      "resultado_acumulado_a_fecha": 420.0,
      "objetivo_acumulado_a_fecha": 405.0,
      "progreso_dia_pct": 115.6,
      "progreso_acumulado_pct": 103.7,
      "semaforo_dia": "verde",
      "semaforo_acumulado": "verde"
    },
    {
      "kpi_id": 2,
      "codigo": "DISPERSION_KM",
      "nombre": "Dispersion de recorrido",
      "unidad": "km",
      "tipo_acumulacion": "promedio",
      "mayor_es_mejor": false,
      "condicion": "between",
      "condicion_simbolo": "entre",
      "objetivo_anual": 0.0,
      "valor_min": 8.0,
      "valor_max": 12.0,
      "tiene_resultado": false,
      "resultado_dia": null,
      "objetivo_dia": null,
      "resultado_acumulado_a_fecha": 10.3,
      "objetivo_acumulado_a_fecha": null,
      "progreso_dia_pct": 0.0,
      "progreso_acumulado_pct": 0.0,
      "semaforo_dia": "gris",
      "semaforo_acumulado": "verde"
    }
  ]
}
```
- Campos del KPI:
  - `tiene_resultado`: `true` si hay un valor cargado para esa fecha exacta.
  - `resultado_dia`: valor del dia (`null` si `tiene_resultado` es `false`).
  - `objetivo_dia`: objetivo del dia. Para `suma`: `objetivo_anual / dias_en_anio` (proporcional). Para `promedio`/`ultimo`: `objetivo_anual` (fijo — no se proratea). Para `between`: `null`.
  - `resultado_acumulado_a_fecha`: acumulado del empleado desde el 1 de enero hasta la fecha (segun `tipo_acumulacion`). `null` si no hay ningun resultado en el periodo.
  - `objetivo_acumulado_a_fecha`: objetivo proporcional acumulado hasta la fecha. `null` para `between`.
  - `semaforo_dia`: `"gris"` si `tiene_resultado` es `false`.
  - `semaforo_acumulado`: `"gris"` si `resultado_acumulado_a_fecha` es `null`.
- Si el empleado no tiene sector asignado, `sector.id` es `null` y `kpis` es `[]`.
- Response 400:
  - `{"error":"El parametro fecha es obligatorio (YYYY-MM-DD)."}`
  - `{"error":"Fecha invalida. Use formato YYYY-MM-DD."}`
  - `{"error":"La fecha no puede ser futura."}`
- Response 500: `{"error":"No se pudieron obtener los KPIs del dia."}`

---

### Premios y concursos

#### 38. `GET /api/v1/mobile/me/premios?anio=YYYY`
- Premios/rankings mensuales obtenidos por el empleado autenticado.
- `anio`: ano a consultar (opcional, default = ano actual del servidor).
- Devuelve siempre los 12 meses del ano para que Flutter pueda pintar tarjetas mes por mes.
- Response 200:
```json
{
  "anio": 2026,
  "sector": {
    "id": 3,
    "nombre": "Logistica"
  },
  "resumen": {
    "total_premios": 3,
    "mejor_ranking": 1,
    "primeros_puestos": 1,
    "podios": 2
  },
  "meses": [
    {
      "mes": 1,
      "nombre": "Enero",
      "premios": [
        {
          "id": 15,
          "periodo": "2026-01",
          "periodo_year": 2026,
          "periodo_month": 1,
          "mes_nombre": "Enero",
          "ranking": 1,
          "observaciones": null,
          "concurso": {
            "id": 2,
            "codigo": "SEGURIDAD",
            "nombre": "Premio de seguridad",
            "descripcion": null,
            "alcance": "global",
            "sector": null
          },
          "sector_empleado": {
            "id": 3,
            "nombre": "Logistica"
          }
        }
      ]
    },
    {
      "mes": 2,
      "nombre": "Febrero",
      "premios": []
    }
  ]
}
```
- `concurso.alcance`:
  - `global`: concurso comun a todos los sectores, por ejemplo Seguridad.
  - `sector`: concurso propio de un sector.
- Si el empleado salio 1ro en enero, 3ro en marzo y 4to en abril, esos tres meses tienen un item en `premios`; los meses sin premio devuelven `premios: []`.
- Response 400: `{"error":"Ano invalido."}`
- Response 500: `{"error":"No se pudieron obtener los premios."}`

---

### Seguridad

#### 39. `GET /api/v1/mobile/me/eventos-seguridad?page=&per=&tipo_evento=`
- Lista paginada de eventos de seguridad (ej. QR fuera de geocerca).
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

---

### Trivia Operativa

Prefijo: `/api/v1/trivia`
Auth: Bearer JWT (mismo token mobile).

Respuestas exitosas: `{"success": true, "data": ...}`
Respuestas de error: `{"success": false, "error": "mensaje"}`

---

#### 40. `GET /api/v1/trivia/estado`
- Estado general del módulo trivia para el empleado autenticado.
- Indica si hay trivia activa, si ya participó o tiene una participación en progreso, y los datos de su última participación.
- Response 200 (sin trivia activa):
```json
{
  "success": true,
  "data": {
    "hay_trivia_activa": false,
    "trivia": null,
    "ya_participo": false,
    "participacion": null
  }
}
```
- Response 200 (con trivia activa, sin participar aún):
```json
{
  "success": true,
  "data": {
    "hay_trivia_activa": true,
    "trivia": {
      "id": 3,
      "titulo": "Trivia Mayo 2026",
      "descripcion": "Preguntas de logística y seguridad.",
      "fecha_inicio": "2026-05-24T08:00:00",
      "fecha_fin": "2026-05-31T23:59:00",
      "estado": "activa",
      "premio": "Vale de consumo $5000",
      "mensaje_ganador": "¡Sos el campeón del mes!",
      "anio": 2026
    },
    "ya_participo": false,
    "en_progreso": false,
    "participacion": null
  }
}
```
- Response 200 (ya completó):
```json
{
  "success": true,
  "data": {
    "hay_trivia_activa": true,
    "trivia": {"id": 3, "titulo": "Trivia Mayo 2026", "...": "..."},
    "ya_participo": true,
    "en_progreso": false,
    "participacion": {
      "estado_resultado": "completado",
      "puntos_total": 80,
      "correctas": 8,
      "incorrectas": 2,
      "tiempo_total_segundos": 142,
      "posicion": null,
      "es_ganador": false
    }
  }
}
```

---

#### 41. `GET /api/v1/trivia/activa`
- Devuelve los datos de la trivia activa para el empleado (sin preguntas).
- Response 200:
```json
{
  "success": true,
  "data": {
    "id": 3,
    "titulo": "Trivia Mayo 2026",
    "descripcion": "Preguntas de logística y seguridad.",
    "fecha_inicio": "2026-05-24T08:00:00",
    "fecha_fin": "2026-05-31T23:59:00",
    "estado": "activa",
    "premio": "Vale de consumo $5000",
    "mensaje_ganador": "¡Sos el campeón del mes!",
    "anio": 2026
  }
}
```
- Response 404: `{"success":false,"error":"No hay trivia activa."}`

---

#### 42. `POST /api/v1/trivia/iniciar`
- Registra el inicio de la participación del empleado y devuelve las preguntas.
- **Las respuestas correctas NO se incluyen en la respuesta.**
- No requiere body.
- Response 200:
```json
{
  "success": true,
  "data": {
    "trivia_id": 3,
    "titulo": "Trivia Mayo 2026",
    "descripcion": "Preguntas de logística y seguridad.",
    "fecha_fin": "2026-05-31T23:59:00",
    "preguntas": [
      {
        "id": 101,
        "trivia_id": 3,
        "texto": "¿Cuántos bultos caben en un pallet estándar?",
        "opcion_a": "60",
        "opcion_b": "72",
        "opcion_c": "80",
        "opcion_d": "48",
        "puntos": 10,
        "orden": 0
      },
      {
        "id": 102,
        "trivia_id": 3,
        "texto": "¿Cuál es el EPP obligatorio en almacén?",
        "opcion_a": "Guantes",
        "opcion_b": "Casco",
        "opcion_c": "Casco y calzado de seguridad",
        "opcion_d": "Ninguno",
        "puntos": 15,
        "orden": 1
      }
    ]
  }
}
```
- Response 200 (participación en progreso ya existente — Flutter debe reanudar):
```json
{
  "success": true,
  "en_progreso": true,
  "message": "Tenés una participación en progreso para esta trivia.",
  "data": {
    "trivia_id": 3,
    "titulo": "Trivia Mayo 2026",
    "preguntas": ["..."]
  }
}
```
- Response 404: `{"success":false,"error":"No hay trivia activa disponible para vos."}`
- Response 409 (ya completó): `{"success":false,"error":"Ya participaste en esta trivia."}`
- Nota: la respuesta correcta (`respuesta_correcta`) nunca se incluye en `preguntas`.

---

#### 43. `POST /api/v1/trivia/finalizar`
- Envía todas las respuestas del empleado. El backend calcula puntaje, correctas, incorrectas y tiempo.
- Request:
```json
{
  "trivia_id": 3,
  "respuestas": [
    {
      "pregunta_id": 101,
      "respuesta": "B",
      "tiempo_respuesta_segundos": 8
    },
    {
      "pregunta_id": 102,
      "respuesta": "C",
      "tiempo_respuesta_segundos": 12
    }
  ]
}
```
- `respuesta`: `"A"` | `"B"` | `"C"` | `"D"` (mayúscula).
- `tiempo_respuesta_segundos`: opcional; segundos que tardó el empleado en responder esa pregunta.
- Response 200:
```json
{
  "success": true,
  "data": {
    "trivia_id": 3,
    "puntos_total": 25,
    "correctas": 2,
    "incorrectas": 0,
    "tiempo_total_segundos": 142,
    "total_preguntas": 2
  }
}
```
- Response 400: `{"success":false,"error":"trivia_id requerido."}`
- Response 404: `{"success":false,"error":"No iniciaste la participación en esta trivia."}`
- Response 409: `{"success":false,"error":"Ya enviaste tus respuestas para esta trivia."}`
- Response 410: `{"success":false,"error":"Esta trivia ya fue finalizada."}`
- Importante: el backend valida las respuestas contra las preguntas activas de la trivia. Si el empleado omite una pregunta, se cuenta como incorrecta.

---

#### 44. `GET /api/v1/trivia/ranking/<trivia_id>`
- Ranking de una trivia. Disponible para trivias activas y finalizadas.
- Orden: mayor puntaje → menor tiempo → inicio más temprano → fin más temprano.
- Response 200:
```json
{
  "success": true,
  "data": {
    "trivia": {
      "id": 3,
      "titulo": "Trivia Mayo 2026",
      "estado": "finalizada",
      "premio": "Vale de consumo $5000",
      "anio": 2026
    },
    "ranking": [
      {
        "posicion": 1,
        "empleado_id": 12,
        "empleado_dni": "30111222",
        "empleado_nombre": "Lopez Ana",
        "puntos_total": 80,
        "correctas": 8,
        "incorrectas": 2,
        "tiempo_total_segundos": 98,
        "es_ganador": true
      },
      {
        "posicion": 2,
        "empleado_id": 15,
        "empleado_dni": "25333444",
        "empleado_nombre": "Gomez Carlos",
        "puntos_total": 80,
        "correctas": 8,
        "incorrectas": 2,
        "tiempo_total_segundos": 120,
        "es_ganador": false
      }
    ]
  }
}
```
- Response 404: `{"success":false,"error":"Trivia no encontrada."}`

---

#### 45. `GET /api/v1/trivia/historial?page=1&per_page=10`
- Lista de trivias finalizadas con datos del ganador de cada una.
- Response 200:
```json
{
  "success": true,
  "data": [
    {
      "id": 3,
      "titulo": "Trivia Mayo 2026",
      "descripcion": "Preguntas de logística y seguridad.",
      "fecha_inicio": "2026-05-24T08:00:00",
      "fecha_fin": "2026-05-31T23:59:00",
      "estado": "finalizada",
      "premio": "Vale de consumo $5000",
      "mensaje_ganador": "¡Sos el campeón del mes!",
      "anio": 2026,
      "ganador_nombre": "Lopez Ana",
      "ganador_dni": "30111222",
      "ganador_puntos": 80
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 10
}
```

---

#### 46. `GET /api/v1/trivia/mi-historial`
- Historial completo de participaciones del empleado autenticado.
- Response 200:
```json
{
  "success": true,
  "data": [
    {
      "trivia_id": 3,
      "titulo": "Trivia Mayo 2026",
      "estado_trivia": "finalizada",
      "fecha_inicio": "2026-05-24T08:00:00",
      "fecha_fin": "2026-05-31T23:59:00",
      "premio": "Vale de consumo $5000",
      "puntos_total": 80,
      "correctas": 8,
      "incorrectas": 2,
      "tiempo_total_segundos": 142,
      "posicion": 1,
      "es_ganador": true,
      "estado_resultado": "completado",
      "fecha_inicio_participacion": "2026-05-25T09:14:00",
      "fecha_finalizacion": "2026-05-25T09:16:22"
    }
  ]
}
```

---

#### 47. `GET /api/v1/trivia/ganador/<trivia_id>`
- Ganador oficial de una trivia finalizada.
- Response 200:
```json
{
  "success": true,
  "data": {
    "trivia_id": 3,
    "titulo": "Trivia Mayo 2026",
    "premio": "Vale de consumo $5000",
    "mensaje_ganador": "¡Sos el campeón del mes!",
    "empleado_id": 12,
    "empleado_dni": "30111222",
    "empleado_nombre": "Lopez Ana",
    "puntos_total": 80,
    "tiempo_total_segundos": 98,
    "fecha_registro": "2026-06-01T00:01:00"
  }
}
```
- Response 404: `{"success":false,"error":"Ganador no disponible aún."}`

---

#### 48. `GET /api/v1/trivia/ranking-anual/<anio>`
- Ranking anual acumulado de todos los empleados.
- Orden: mayor puntos acumulados → más trivias ganadas → más correctas → menor tiempo → más participaciones.
- Response 200:
```json
{
  "success": true,
  "anio": 2026,
  "data": [
    {
      "id": 1,
      "anio": 2026,
      "empleado_id": 12,
      "empleado_dni": "30111222",
      "empleado_nombre": "Lopez Ana",
      "puntos_anuales": 240,
      "trivias_participadas": 3,
      "trivias_ganadas": 2,
      "correctas_totales": 26,
      "incorrectas_totales": 4,
      "tiempo_total_anual": 380,
      "posicion": 1,
      "es_ganador_anual": false
    }
  ]
}
```

---

#### 49. `GET /api/v1/trivia/ganador-anual/<anio>`
- Ganador anual definitivo del año indicado.
- Response 200:
```json
{
  "success": true,
  "data": {
    "id": 1,
    "anio": 2026,
    "empleado_id": 12,
    "empleado_dni": "30111222",
    "empleado_nombre": "Lopez Ana",
    "puntos_anuales": 240,
    "trivias_participadas": 3,
    "trivias_ganadas": 2,
    "correctas_totales": 26,
    "incorrectas_totales": 4,
    "tiempo_total_anual": 380,
    "posicion": 1,
    "es_ganador_anual": true
  }
}
```
- Response 404: `{"success":false,"error":"Ganador anual 2026 no disponible aún."}`

---

#### 50. `GET /api/v1/trivia/notificaciones`
- Devuelve las notificaciones de trivia no leídas del empleado.
- Diseñado para polling desde Flutter (no usa push).
- Response 200:
```json
{
  "success": true,
  "data": [
    {
      "id": 7,
      "trivia_id": 3,
      "trivia_titulo": "Trivia Mayo 2026",
      "tipo": "recordatorio_2h",
      "mensaje": "¡Quedan solo 2 horas para participar en 'Trivia Mayo 2026'! No te lo pierdas.",
      "enviada_en": "2026-05-31T21:59:00",
      "fecha_fin_trivia": "2026-05-31T23:59:00"
    }
  ]
}
```
- `tipo`: `recordatorio_24h` | `recordatorio_2h`

---

#### 51. `POST /api/v1/trivia/notificaciones/<id>/leer`
- Marca una notificación puntual como leída.
- No requiere body.
- Response 200: `{"success":true,"data":{"marcada":true}}`

---

#### 52. `POST /api/v1/trivia/notificaciones/leer-todas`
- Marca todas las notificaciones del empleado como leídas.
- No requiere body.
- Response 200: `{"success":true,"data":{"marcadas":true}}`

---

### Calificación de la app

#### 53. `POST /api/v1/mobile/calificar-app`
- Envía la valoración del empleado autenticado sobre la experiencia de uso de la app.
- Un empleado solo puede calificar **una vez por versión**. Si envía `version_app: null` o lo omite, solo puede calificar una vez con versión nula.
- Request:
```json
{
  "puntuacion": 4,
  "comentario": "Muy fácil de usar, solo falta el modo oscuro",
  "pantalla": "asistencia",
  "version_app": "1.20.3"
}
```
  | Campo | Tipo | Requerido | Notas |
  |---|---|---|---|
  | `puntuacion` | int | Sí | Entero entre 1 y 5 |
  | `comentario` | string | No | Texto libre, máx. recomendado 500 chars |
  | `pantalla` | string | No | Nombre de la pantalla o sección desde donde se lanzó el diálogo |
  | `version_app` | string | No | Versión de la app instalada. Si se omite se registra como nula |

- Response 201:
```json
{"ok": true, "id": 42}
```
- Response 400 (puntuacion fuera de rango o ausente):
```json
{"ok": false, "error": "puntuacion debe ser un entero entre 1 y 5"}
```
- Response 409 (ya calificó esa versión):
```json
{"ok": false, "error": "Ya calificaste esta versión de la app"}
```

#### Flujo recomendado Flutter — Calificación de la app

Implementado via `AppRatingService` + `FlutterSecureStorage` (con `encryptedSharedPreferences: true` en Android).

**Claves de storage por versión (`version` = valor de `PackageInfo.version`):**
| Clave | Descripcion |
|---|---|
| `rating_sessions_{version}` | Contador de sesiones acumuladas para esta versión |
| `rating_rated_{version}` | `"1"` si el usuario ya calificó esta versión |
| `rating_dismissals_{version}` | Contador de veces que el usuario descartó el diálogo |

**Lógica `shouldShowDialog()`:**
1. Si `rating_rated_{version} == "1"` → no mostrar.
2. Si `rating_dismissals_{version} >= maxDismissals` (default 2) → no mostrar.
3. Incrementar `rating_sessions_{version}`; si el nuevo valor >= `minSessions` (default 3) → mostrar.

**Al enviar calificación (`submitRating`):**
- Obtiene versión actual via `PackageInfo.fromPlatform()` y llama `POST /calificar-app` con `version_app`.
- Si `ok: true` → escribe `rating_rated_{version} = "1"` en storage.
- Si `409` → el backend ya tiene la calificación; marcar igualmente `rating_rated_{version} = "1"`.

**Al descartar (`markDismissed`):**
- Incrementa `rating_dismissals_{version}`. Cuando llega a `maxDismissals`, no se vuelve a mostrar para esta versión.

---

#### Flujo recomendado Flutter — Trivia

1. Al abrir el módulo: `GET /api/v1/trivia/estado`
   - Si `hay_trivia_activa=false` → mostrar pantalla de "sin trivia disponible".
   - Si `ya_participo=true` → mostrar resultado previo y ranking.
   - Si `en_progreso=true` → ir directamente a `POST /iniciar` para recuperar preguntas.
   - Si ninguna de las anteriores → mostrar botón "Jugar".
2. Al tocar "Jugar": `POST /api/v1/trivia/iniciar`
   - Guardar localmente el `trivia_id` y `fecha_fin`.
3. El empleado responde todas las preguntas.
4. Al finalizar: `POST /api/v1/trivia/finalizar` con todas las respuestas.
5. Mostrar resultado (`puntos_total`, `correctas`, `incorrectas`).
6. Opcional: `GET /api/v1/trivia/ranking/<trivia_id>` para ver la posición en tiempo real.
7. Para notificaciones: polling periódico a `GET /api/v1/trivia/notificaciones` y marcar leídas.

#### Reglas de negocio — Trivia

- Un empleado solo puede participar **una vez** por trivia. El backend valida esto independientemente del frontend.
- Las preguntas se entregan **sin la respuesta correcta**. Nunca se expone `respuesta_correcta` en respuestas de la API.
- Solo se puede responder una trivia mientras su estado sea `activa` y esté dentro del horario `fecha_inicio` – `fecha_fin`.
- Si el empleado omite una pregunta en el body de `/finalizar`, se cuenta como incorrecta con 0 puntos.
- El ranking definitivo se calcula automáticamente cuando la trivia finaliza (scheduler o finalización manual desde el panel admin).

---

## Errores estandar

- `400`: validacion de payload/formato
- `401`: login/token invalido o vencido
- `403`: fuera de geocerca o usuario no permitido
- `404`: recurso no encontrado
- `409`: conflicto (ej. salida ya registrada, cooldown por doble scan, edicion de justificacion no pendiente)
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

---

## Change log

### 1.21.5 (2026-05-28)
- Flutter — nueva solapa **"Mes en curso"** en `KpisSectorPage`:
  - Se agrega una segunda pestaña ("Mes en curso") junto a la existente ("Resumen"). El contenido de "Resumen" queda intacto.
  - Muestra un **calendario mensual del mes en curso** (semana lunes–domingo). Los días pasados y hoy son tapeables; los días futuros están deshabilitados.
  - **Dots de datos sin llamada extra**: los días que ya tienen al menos un resultado cargado muestran un punto debajo del número. Se derivan de `series_diaria[].puntos[].resultado_dia` ya cargados en la llamada a endpoint 37A (`GET /me/kpis-sector/resumen?include_series=true`), sin llamadas adicionales.
  - **Tap en un día**: llama al endpoint 37B (`GET /me/kpis-sector/dia?fecha=YYYY-MM-DD`) y muestra las tarjetas de KPI para esa fecha. Las respuestas se cachean en memoria durante la sesión — tocar un día ya consultado no genera nueva llamada a la red.
  - Cada tarjeta de KPI muestra: nombre, código, semaforo, `resultado_dia`, `objetivo_dia` y `resultado_acumulado_a_fecha`.
  - Si el día no tiene ningún registro (`tiene_resultado = false` para todos los KPIs), se muestra un estado vacío "Sin registros para este día."
  - Sin cambios de payload ni status codes en el backend.

### 1.21.4 (2026-05-28)
- Documentacion explicita de `tipo_acumulacion = "ultimo"` en endpoints 37, 37A y 37B:
  - `resultado_acumulado` / `resultado_mes` para `ultimo` es el **valor mas reciente por fecha**, no un promedio ni una suma.
  - Ideal para indicadores tipo snapshot que se reemplazan al cambiar (NPS, stock, tasas).
  - `objetivo_dia` para `ultimo` es `objetivo_anual` (fijo, igual que `promedio`); no se proratea.
  - Sin cambio de payload ni status codes — solo aclaracion semantica y de negocio.
- Panel web: formulario de KPI actualizado con descripciones claras por tipo de acumulacion e indicaciones de uso (NPS → Ultimo, satisfaccion → Promedio, bultos → Suma).
- Panel web: listado de KPIs ahora muestra el tipo de acumulacion con badge de color (azul=suma, naranja=promedio, verde=ultimo) para facilitar la revision de configuracion.

### 1.21.3 (2026-05-28)
- Nuevo endpoint `GET /me/kpis-sector/dia?fecha=YYYY-MM-DD` (endpoint 37B):
  - Snapshot de todos los KPIs activos del sector para una fecha concreta.
  - Siempre devuelve una fila por KPI aunque no haya resultado ese día exacto.
  - Cada fila incluye: `tiene_resultado`, `resultado_dia`, `objetivo_dia`, `resultado_acumulado_a_fecha`, `objetivo_acumulado_a_fecha`, `progreso_dia_pct`, `progreso_acumulado_pct`, `semaforo_dia`, `semaforo_acumulado`.
  - Acumulado calculado desde el 1 de enero del año de la fecha consultada.
  - `fecha` requerida, no puede ser futura. 400 si falta, es inválida o es futura.

### 1.21.2 (2026-05-28)
- `GET /me/kpis-sector/resumen` — nueva serie diaria opcional:
  - Params opcionales: `include_series=true` y `series_dias=N` (1–365, default 60).
  - Si `include_series=true`, el payload incluye `series_diaria`: lista de KPIs del sector con campo `puntos` (una entrada por dia con resultado real).
  - Cada punto expone: `resultado_dia`, `objetivo_dia`, `resultado_acumulado_a_fecha`, `objetivo_acumulado_a_fecha`, `progreso_dia_pct`, `progreso_acumulado_pct`, `semaforo_dia`, `semaforo_acumulado`.
  - Los acumulados se computan desde el inicio del anio aunque la ventana de display sea menor.
  - Para KPIs `between`, `objetivo_dia` y `objetivo_acumulado_a_fecha` son `null`; se usa `valor_min`/`valor_max`.
  - `meta` ahora incluye siempre `include_series` (bool) y `series_dias` (int o null).
  - Sin `include_series`, el payload es identico al de 1.21.1 (compatible).
  - Nuevo 400: `{"error":"series_dias invalido. Use un entero entre 1 y 365."}`.

### 1.21.1 (2026-05-28)
- Aclaracion de contrato para KPIs mobile:
  - Los resultados provienen de importaciones CSV del panel web.
  - `codigo_kpi` se resuelve por el sector del empleado.
  - Al importar datos del mes actual, backend reemplaza ese mes para los empleados incluidos en el CSV antes de insertar los nuevos datos.
  - Los meses historicos no se limpian masivamente; solo se insertan/actualizan registros coincidentes.
- No cambia el payload ni los status codes de `GET /me/kpis-sector` ni `GET /me/kpis-sector/resumen`.

### 1.21.0 (2026-05-28)
- Nuevo endpoint mobile de KPIs sectoriales enriquecidos:
  - `GET /me/kpis-sector/resumen?anio=YYYY&limit_meses=N`
- No modifica el endpoint existente `GET /me/kpis-sector`.
- Agrega vistas para Flutter:
  - `vista_actual.kpis`: misma informacion de la vista anual actual.
  - `ultimo_cargado`: ultimo resultado de KPI cargado, con `fecha_resultado` y `cargado_at`.
  - `meses_cerrados`: resultados por KPI agrupados por meses calendario cerrados.
- `limit_meses` permite pedir de 1 a 12 meses cerrados; default 6.

### 1.20.5 (2026-05-25)
- **Corrección de flujo calificación (endpoint 53):** el flujo recomendado ahora describe la implementación real con `AppRatingService` + `FlutterSecureStorage`. Se documentan las claves de storage, la lógica de `shouldShowDialog` (`minSessions=3`, `maxDismissals=2`) y el comportamiento ante `409`.
- **Panel web:** sección "Pedidos Empleados" separada del grupo "Asistencia" en la navegación lateral. Incluye Adelantos, Pedidos mercadería e Importar catálogo.

### 1.20.4 (2026-05-24)
- **Telemetría de sesiones mobile** — registro automático de cada login en tabla `mobile_sesiones`.
  - `POST /auth/login` acepta 3 campos opcionales nuevos: `platform`, `device_model`, `app_version`. Totalmente retrocompatible — si Flutter no los envía, funciona igual y se guardan como nulos.
  - `POST /auth/refresh` actualiza `fecha_ultimo_request` de la sesión en curso (sin cambios en la respuesta).
  - El JWT ahora incluye `sesion_id` internamente. Flutter no necesita leerlo.
  - Panel admin web en `/mobile-stats/` (solo admin): KPIs de sesiones hoy/7d/30d, distribución Android/iOS, versiones activas y gráfico de actividad diaria.
  - Requiere `device_info_plus` en Flutter para enviar modelo del dispositivo. Ver flujo recomendado en endpoint 1.

### 1.20.3 (2026-05-24)
- **Nuevo módulo: Calificación de la app** — endpoint 53.
  - `POST /api/v1/mobile/calificar-app` — envía puntuación 1–5, comentario opcional, pantalla y versión de la app.
  - Un empleado puede calificar una vez por versión de app (`version_app` nullable; la unicidad por NULL se controla a nivel aplicación).
  - Panel admin web en `/admin/calificaciones-app/` con KPIs, barra de distribución de estrellas y tabla filtrable por fecha, versión, puntuación y sector.
  - Tabla MySQL: `app_calificaciones` (migración `20260524_03`).

### 1.20.2 (2026-05-24)
- Changelog reorganizado: entrada 1.20.2 ya documentada — ver abajo.

### 1.20.0 (2026-05-24)
- **Nuevo módulo: Trivia Operativa** — prefijo `/api/v1/trivia/`
- Nuevos endpoints (40–52):
  - `GET /trivia/estado` — estado general para el empleado (hay trivia, ya participó, resultado propio).
  - `GET /trivia/activa` — datos de la trivia activa disponible.
  - `POST /trivia/iniciar` — registra inicio de participación; devuelve preguntas sin respuesta correcta.
  - `POST /trivia/finalizar` — recibe todas las respuestas, calcula puntaje, correctas, tiempo.
  - `GET /trivia/ranking/<trivia_id>` — ranking en tiempo real de una trivia.
  - `GET /trivia/historial` — trivias finalizadas con ganador (paginado).
  - `GET /trivia/mi-historial` — historial de participaciones del empleado autenticado.
  - `GET /trivia/ganador/<trivia_id>` — ganador oficial de una trivia.
  - `GET /trivia/ranking-anual/<anio>` — ranking anual acumulado.
  - `GET /trivia/ganador-anual/<anio>` — ganador anual definitivo.
  - `GET /trivia/notificaciones` — notificaciones no leídas (polling Flutter).
  - `POST /trivia/notificaciones/<id>/leer` — marca una notificación como leída.
  - `POST /trivia/notificaciones/leer-todas` — marca todas como leídas.
- Reglas de negocio:
  - Un empleado solo puede participar una vez por trivia (validación backend con UNIQUE constraint).
  - La respuesta correcta nunca se expone en la API.
  - Solo se puede jugar dentro del horario `fecha_inicio`–`fecha_fin` con estado `activa`.
  - Preguntas omitidas en `/finalizar` se cuentan como incorrectas.
  - Ranking definitivo: mayor puntaje → menor tiempo → inicio más temprano → fin más temprano.
  - Ranking anual: mayor puntaje acumulado → más trivias ganadas → más correctas → menor tiempo → más participaciones.
- Scheduler automático (APScheduler):
  - Activa trivias cuya `fecha_inicio` llegó (cada 2 minutos).
  - Finaliza trivias vencidas y calcula ranking definitivo (cada 2 minutos).
  - Genera notificaciones a empleados sin participar: recordatorio 24h y 2h antes del fin (cada 1 hora).
- Panel admin web: `/admin/trivias/` con CRUD de trivias, preguntas, visualización de ranking y finalización manual.

### 1.19.0 (2026-05-18)
- **Legajo — documentacion bloqueada para empleados:**
  - `GET /me/legajo/adjuntos/<id>` siempre devuelve `403 No autorizado`. Los empleados no pueden descargar documentacion.
  - `GET /me/legajo/eventos` y `GET /me/legajo/eventos/<id>`: eliminados los campos `adjuntos_count` y `adjuntos` de todas las respuestas.
  - `legajo.recientes` dentro de `GET /me/dashboard` actualizado con el mismo esquema reducido.
- **Nuevo endpoint `GET /me/legajo/historial-por-tipo`:**
  - Devuelve todos los tipos de evento activos con `total`, `vigentes` y `ultima_fecha` para el empleado autenticado.
  - Incluye tipos con `total: 0`.
  - Ordenado por total descendente, luego nombre.

### 1.18.0 (2026-05-16)
- Se completa el contrato mobile de legajo:
  - `GET /me/legajo/resumen`
  - `GET /me/legajo/tipos-evento`
  - `GET /me/legajo/eventos` con filtros `desde`, `hasta`, `severidad`, `q`, `tipo_id`, `estado`
  - `GET /me/legajo/eventos/<id>` con adjuntos
  - `GET /me/legajo/adjuntos/<id>` para descarga con Bearer JWT
- Las respuestas nuevas de legajo usan `ok` y errores JSON con `ok=false`.
- Los adjuntos mobile quedan scoped al empleado autenticado.

### 1.20.2 (2026-05-24)
- `GET /vacaciones/resumen` — campos nuevos:
  - `desglose_corresponde`: array `[{concepto, dias}]` listo para renderizar cada componente de `dias_corresponden`. Solo incluye conceptos con valor > 0. Soluciona el problema de mostrar "48 días" sin contexto; el app puede armar "35 Base LCT + 13 Compensatorios = 48 días".
  - `dias_trabajados_porcentaje`: porcentaje de dias trabajados sobre el total habil del periodo. Para mostrar "66 de 102 días hábiles (64.7%)" en lugar de la fraccion cruda.
  - `umbral_proporcional_pct`: siempre `50.0`. Indica el minimo % para no sufrir reduccion proporcional. Util para mostrar un indicador de progreso en la pantalla de saldo.
- `GET /vacaciones/movimientos` — campos nuevos por movimiento:
  - `es_reversion`: `true` si el movimiento revierte otro (no afecta saldo, mostrar atenuado).
  - `afecta_saldo`: `false` para rechazados y reversiones. Cuando es `false`, el item debe mostrarse como historial, sin impactar el saldo visible. Incluye aviso UX recomendado.
- Documentacion UX recomendada: padding inferior minimo de 80px en la lista de movimientos para evitar que el FAB flotante tape el ultimo item.
- Tabla completa de referencia de todos los campos de `vacaciones` en el resumen.

### 1.20.1 (2026-05-24)
- `GET /vacaciones/resumen`: respuesta completa documentada con todos los campos devueltos (`dias_habiles_anio_total`, `dias_habiles_evaluados`, `fecha_evaluacion_trabajo`, `aplica_control_proporcional`).
- Se documenta la logica de `dias_compensatorios`: dias extra acreditados por RRHH por sector o empleado, independientes de las vacaciones base. Se suman a `dias_corresponden`.
- Formula explicita: `dias_corresponden = dias_base + dias_compensatorios + dias_ajustes`. Tomar vacaciones descuenta de este total indiferentemente de su origen.
- Flujo Flutter recomendado para pantalla de saldo de vacaciones incluido.
- Correccion del calculo proporcional para nuevos ingresos: el denominador ahora usa los dias habiles desde la fecha de ingreso (no desde el 1 de enero), evitando penalizar incorrectamente a empleados con ingreso posterior a enero.

### 1.17.0 (2026-05-15)
- Nuevos endpoints mobile para vacaciones con saldo LCT:
  - `GET /vacaciones/resumen?anio=YYYY`
  - `GET /vacaciones/movimientos?anio=YYYY`
  - `POST /vacaciones/solicitar`
- `POST /vacaciones/solicitar` valida saldo disponible contra `dias_disponibles_con_pendientes` y crea un movimiento `tomado` en estado `pendiente`.
- Se documenta que `/me/vacaciones*` queda como compatibilidad sobre movimientos, mientras el flujo mobile recomendado usa los endpoints de saldo/movimientos.

### 1.16.1 (2026-05-13)
- `POST /me/fichadas/scan`: `qr_token` acepta JWT directo, `Bearer`, URL con query o JSON con `qr_token`.
- `POST /me/fichadas/scan`: errores QR devuelven `code` especifico (`qr_token_invalid_signature`, `qr_token_expired`, `qr_inactive`, etc.).
- `POST /me/qr`: default real de `vigencia_segundos` alineado al contrato (`2592000`, 30 dias).
- QR puerta: los QRs generados desde el panel quedan registrados y pueden inactivarse; un QR inactivo se rechaza en mobile.

### 1.15.0 (2026-04-20)
- `GET /me/kpis-sector`: nuevos campos por KPI: `condicion`, `condicion_simbolo`, `valor_min`, `valor_max`.
- Soporte condicion `between`: el semaforo evalua si el resultado cae dentro del rango [valor_min, valor_max].
- Semaforo `between`: verde=dentro del rango, amarillo=dentro del 10% del margen exterior, rojo=fuera.
- Para KPIs `promedio`/`ultimo`, el ritmo esperado ya no aplica fraccion anual (siempre compara contra el objetivo completo).

### 1.14.0 (2026-04-19)
- Nuevo endpoint KPIs sectoriales:
  - `GET /me/kpis-sector?anio=YYYY`
- Devuelve por KPI: objetivo anual del sector, resultado acumulado del empleado, semaforo y recomendacion.
- Semaforo: `verde` / `amarillo` / `rojo` basado en ritmo esperado lineal vs real.
- Los resultados se cargan diariamente via CSV en el panel web.

### 1.13.1 (2026-04-19)
- Se completa el contrato mobile de pedidos de mercaderia con:
  - esquema explicito de `PedidoMercaderiaItem`
  - flujo recomendado para Flutter
  - validaciones de alta
  - respuestas de error para edicion y cancelacion

### 1.13.0 (2026-04-18)
- Nuevos endpoints de pedidos de mercaderia para mobile:
  - `GET /me/pedidos-mercaderia/resumen`
  - `GET /me/pedidos-mercaderia/estado`
  - `GET /me/pedidos-mercaderia/articulos`
  - `GET /me/pedidos-mercaderia`
  - `GET /me/pedidos-mercaderia/<id>`
  - `POST /me/pedidos-mercaderia`
  - `PUT /me/pedidos-mercaderia/<id>`
  - `DELETE /me/pedidos-mercaderia/<id>`
- Reglas nuevas de negocio:
  - solo se permite un pedido de mercaderia por empleado por mes calendario
  - un pedido `pendiente` puede editarse o cancelarse
  - las cantidades se informan solo en `bultos`
- `GET /me/pedidos-mercaderia/articulos` expone solo articulos importados con:
  - `Activo = SI`
  - `Anulado = NO`
  - `Usado en dispositivo movil = SI`
  - `TIPO DE PRODUCTO = MERCADERIA`

### 1.12.3 (2026-04-18)
- Nuevo endpoint mobile de resumen para la pantalla inicial:
  - `GET /me/adelantos/resumen`
- Devuelve:
  - `adelanto_mes_actual`
  - `ultimo_adelanto`
  - `total_historial`
  - `pendientes_total`

### 1.12.2 (2026-04-18)
- Nuevo endpoint mobile de detalle de adelanto:
  - `GET /me/adelantos/<id>`

### 1.12.1 (2026-04-18)
- Nuevo endpoint mobile de historial de adelantos:
  - `GET /me/adelantos` (lista paginada con filtro opcional `estado`)
- `AdelantoItem` ahora puede incluir:
  - `resuelto_at`
  - `resuelto_by_usuario`

### 1.12.0 (2026-04-17)
- Nuevos endpoints de adelantos para mobile:
  - `GET /me/adelantos/estado` (consulta si ya existe solicitud en el mes actual)
  - `POST /me/adelantos` (crea la solicitud del mes actual)
- Regla nueva de negocio:
  - solo se permite un adelanto por empleado por mes calendario

### 1.11.0 (2026-03-26)
- Nuevos endpoints: CRUD completo de justificaciones:
  - `GET /me/justificaciones` (lista paginada con filtros `desde`, `hasta`, `estado`)
  - `GET /me/justificaciones/<id>`
  - `POST /me/justificaciones`
  - `PUT /me/justificaciones/<id>` (solo estado `pendiente`)
  - `DELETE /me/justificaciones/<id>` (solo estado `pendiente`)
- Nuevos endpoints: CRUD completo de vacaciones:
  - `GET /me/vacaciones`, `GET /me/vacaciones/<id>`
  - `POST /me/vacaciones`, `PUT /me/vacaciones/<id>`, `DELETE /me/vacaciones/<id>`
- Nuevos endpoints: horarios asignaciones:
  - `GET /me/horarios-asignaciones` (historial)
  - `GET /me/horarios-asignaciones/actual` (con dias de la semana)
- Nuevos endpoints: francos:
  - `GET /me/francos`, `GET /me/francos/<id>`
- Nuevos endpoints: legajo:
  - `GET /me/legajo/eventos` (con filtros `tipo_id`, `estado`)
  - `GET /me/legajo/eventos/<id>`
- Nuevo endpoint dashboard consolidado: `GET /me/dashboard`
  - Combina estadisticas de asistencia + eventos de legajo + vacaciones activas + francos proximos + horario actual
  - Params: `periodo` (`7d`|`30d`|`mes_actual`|`90d`) + override `desde`/`hasta`
- `GET /me/estadisticas` ampliado:
  - 7 nuevos campos en `kpis`: `adherencia_pct`, `horas_promedio`, `horas_totales`, `gps_incidencias`, `dias_laborables`, `dias_con_registro`, `racha_ok`
  - Nuevo campo en `justificaciones`: `tasa_justificacion_pct`
  - Nueva serie en `series`: `semanal` (resumen por semana ISO)

### 1.10.0 (2026-03-09)
- `POST /api/v1/mobile/auth/login` agrega `empleado.imagen_version`.
- `GET /api/v1/mobile/me` agrega `imagen_version`.
- `PUT /api/v1/mobile/me/perfil` agrega `imagen_version` en response.
- `DELETE /api/v1/mobile/me/perfil/foto` agrega `imagen_version` en response (`null`).
- Nuevo endpoint de imagen para cliente mobile: `GET /empleados/imagen/<dni>?v=<imagen_version>` con soporte `ETag/304`.

### 1.9.0 (2026-02-28)
- `PUT /api/v1/mobile/me/perfil` agrega `eliminar_foto=true` para baja de foto.
- Nuevo endpoint `DELETE /api/v1/mobile/me/perfil/foto`.

### 1.8.0 (2026-02-28)
- `PUT /api/v1/mobile/me/perfil` soporta `multipart/form-data` con `foto_file`.

### 1.7.0 (2026-02-27)
- Nuevo endpoint: `GET /api/v1/mobile/me/estadisticas`.

### 1.6.0 (2026-02-25)
- `GET /api/v1/mobile/me/config-asistencia` agrega `cooldown_scan_segundos` e `intervalo_minimo_fichadas_minutos`.
- `POST /api/v1/mobile/me/fichadas/scan` agrega `code` y `cooldown_segundos_restantes` en 409 por doble scan.

### 1.5.0 (2026-02-24)
- Se mantiene `POST /api/v1/mobile/me/fichadas/scan` como endpoint recomendado.
- Se marcan `deprecated`: `/fichadas/entrada` y `/fichadas/salida`.
- Se agrega base URL de produccion.
