# Mapa de fichadas (panel)

**Menú:** Asistencia → Mapa de fichadas (`/mapa-fichadas/`). Muestra dónde fichó cada empleado y si quedó dentro del
radio permitido. La pantalla es solo lectura. Para la calidad del GPS se agregaron tres columnas a `asistencia_marcas`
y tres campos opcionales a la API (ver abajo); la app todavía no los manda.

## Qué muestra

- **Filtros:** fechas (hasta 31 días; por defecto los últimos 7), sucursal, empleado, ingresos o egresos.
- **Mostrar:** todas, solo fuera de radio, o con alertas (fuera de radio, GPS simulado o posición de más de 2 min).
- **Indicadores:** total de fichadas, dentro del radio, fuera del radio, sin ubicación, GPS simulado y posición vieja.
- **Mapa:** cada fichada con ubicación.
  - Verde: dentro del radio. Rojo: fuera. Gris: sin validar.
  - Círculos azules: las sucursales y los puntos de validación (QR), cada uno con su radio.
  - Una fichada fuera de radio tiene una línea punteada hasta su punto de referencia.
  - El halo alrededor de cada punto es la precisión del GPS. Un GPS simulado se marca con un borde violeta.
- **Lista lateral:** las fichadas, primero las que tienen alertas. Al tocar una, el mapa se centra en ella. Se muestran
  hasta 3000 puntos; si hay más, la página avisa que conviene acotar las fechas o los filtros.

## Datos que usa

Todos se guardan ya en cada fichada:
- **`asistencia_marcas`:** `lat`, `lon`, `gps_ok`, `gps_distancia_m`, `gps_tolerancia_m`, `gps_ref_lat` y
  `gps_ref_lon`.
- **`asistencia_marcas`, desde el contrato mobile 1.54.0:** `gps_precision_m`, `gps_simulada` y `gps_edad_s`, que
  manda la app.
- **`sucursales`:** `latitud`, `longitud` y `radio_permitido_m`.

**Sin ubicación** (contadas aparte, no dibujadas): las fichadas manuales, las del egreso automático y las de quien no
dio permiso de GPS.

## Calidad del GPS (contrato mobile 1.54.0)

`POST /me/fichadas/scan`, `/entrada` y `/salida` aceptan tres campos opcionales:

| Campo | Qué es |
|---|---|
| `gps_precision_m` | Precisión de la posición en metros |
| `gps_simulada` | La posición viene de un GPS falso (Android) |
| `gps_edad_s` | Antigüedad de la posición en segundos |

- **Solo se guardan y se muestran:** no cambian la validación del radio.
- **Migración:** `scripts/migrate_20261019_05_gps_calidad.py`, versión `20261019_gps_calidad`.
  - Agrega las tres columnas a `asistencia_marcas`; aceptan vacío y en MySQL 8 se agregan al instante.
  - Reversión: DROP de las tres columnas y borrar la versión de `app_schema_versions`.
- **Pendiente en la app Flutter:** mandar `accuracyM` (que ya mide), `Position.isMocked` y la antigüedad de la posición,
  también en la cola de fichadas sin conexión. Hasta entonces los campos llegan vacíos.
- **Historial de marcas:** todavía no los muestra. Lee la vista `asistencia_marcas_reporte`, que habría que redefinir.

## Técnica

- **Leaflet 1.9.4:** se sirve desde `static/vendor/leaflet`, verificado contra los hashes SRI oficiales, porque la
  política de seguridad (CSP) del panel solo permite scripts propios.
- **Mapa de fondo:** OpenStreetMap, con su atribución. La CSP ya admite imágenes `https:`.
- **Datos en la página:** van como JSON escapado (`<script type="application/json">`) y los lee
  `static/js/mapa-fichadas.js`. Los textos de los popups se escapan.
- **Sin conexión a OpenStreetMap:** el fondo se ve gris, pero los puntos, la lista y los indicadores siguen
  funcionando.

## Permiso

Módulo `mapa_fichadas` (acción `ver`), por defecto solo para admin y RR. HH.: la ubicación es un dato personal (Ley
25.326). A otros usuarios se les habilita a mano en Usuarios del panel.
