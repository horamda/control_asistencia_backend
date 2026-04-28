# Contrato API Mobile v1

Version de contrato: 1.15.0
Fecha de corte: 2026-04-20
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

### Auth

#### 1. `POST /api/v1/mobile/auth/login`
- Request:
```json
{"dni":"30111222","password":"secreta123"}
```
- Response 200:
```json
{
  "token":"<jwt>",
  "empleado":{"id":12,"dni":"30111222","nombre":"Ana","apellido":"Lopez","empresa_id":1,"foto":"https://.../30111222.jpg","imagen_version":"1709294400"}
}
```

#### 2. `POST /api/v1/mobile/auth/refresh`
- Response 200:
```json
{"token":"<jwt>"}
```

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
        "tipo_id":3,
        "tipo_codigo":"llamado_atencion",
        "tipo_nombre":"Llamado de atencion",
        "fecha_evento":"2026-03-10",
        "fecha_desde":null,
        "fecha_hasta":null,
        "titulo":"Llegada tarde reiterada",
        "descripcion":"Tercer llamado en el mes",
        "estado":"vigente",
        "severidad":"grave"
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

---

### Adelantos

#### 27A. `GET /api/v1/mobile/me/adelantos/resumen`
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

#### 27B. `GET /api/v1/mobile/me/adelantos/estado`
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

#### 27C. `GET /api/v1/mobile/me/adelantos?page=&per_page=&estado=`
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

#### 27D. `GET /api/v1/mobile/me/adelantos/<id>`
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

#### 27E. `POST /api/v1/mobile/me/adelantos`
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

#### 27F. `GET /api/v1/mobile/me/pedidos-mercaderia/resumen`
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

#### 27G. `GET /api/v1/mobile/me/pedidos-mercaderia/estado`
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

#### 27H. `GET /api/v1/mobile/me/pedidos-mercaderia/articulos?q=&page=&per_page=`
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

#### 27I. `GET /api/v1/mobile/me/pedidos-mercaderia?page=&per_page=&estado=`
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

#### 27J. `GET /api/v1/mobile/me/pedidos-mercaderia/<id>`
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

#### 27K. `POST /api/v1/mobile/me/pedidos-mercaderia`
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

#### 27L. `PUT /api/v1/mobile/me/pedidos-mercaderia/<id>`
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

#### 27M. `DELETE /api/v1/mobile/me/pedidos-mercaderia/<id>`
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

#### 32. `GET /api/v1/mobile/me/legajo/eventos?tipo_id=&estado=&page=&per_page=`
- Lista paginada de eventos del legajo del empleado.
- `estado`: `vigente` | `anulado` (opcional)
- Response 200:
```json
{
  "items":[
    {
      "id":45,
      "tipo_id":3,
      "tipo_codigo":"llamado_atencion",
      "tipo_nombre":"Llamado de atencion",
      "fecha_evento":"2026-03-10",
      "fecha_desde":null,
      "fecha_hasta":null,
      "titulo":"Llegada tarde reiterada",
      "descripcion":"Tercer llamado en el mes",
      "estado":"vigente",
      "severidad":"grave"
    }
  ],
  "total":1,
  "page":1,
  "per_page":20
}
```
- `severidad`: `grave` | `media` | `leve` | `null`
- `estado`: `vigente` | `anulado`

#### 33. `GET /api/v1/mobile/me/legajo/eventos/<id>`
- Response 200: objeto evento (mismo esquema).
- Response 404: `{"error":"Evento no encontrado"}`

---

### KPIs Sectoriales

#### 35. `GET /api/v1/mobile/me/kpis-sector?anio=YYYY`
- KPIs del sector del empleado autenticado para el año solicitado.
- `anio`: año a consultar (opcional, default = año actual del servidor).
- Para cada KPI muestra resultado acumulado vs objetivo anual del sector, con semaforo y recomendacion.
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
  - `mayor_es_mejor`: `true` si mayor valor es mejor resultado
  - `condicion`: `gte` | `lte` | `eq` | `between`
  - `condicion_simbolo`: `≥` | `≤` | `=` | `entre`
  - `objetivo_anual`: objetivo simple del sector (0 si condicion es `between` o no configurado)
  - `valor_min` / `valor_max`: limites del rango (`null` salvo condicion `between`)
  - `resultado_acumulado`: valor acumulado del empleado en el año segun tipo_acumulacion
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

---

### Seguridad

#### 34. `GET /api/v1/mobile/me/eventos-seguridad?page=&per=&tipo_evento=`
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
