"""Geolocalizacion de una sucursal en el panel (solo lectura): donde fichan de verdad sus empleados y si los QR de
puerta activos quedaron con otra ubicacion.

- Sugerencia: el punto central (mediana de latitud y de longitud, que no se mueve por unas pocas fichadas sueltas) de
  las fichadas con GPS de los empleados de la sucursal en los ultimos DIAS dias, con cuantas quedan cerca.
- QR: la ubicacion contra la que se valida una fichada va firmada dentro del QR impreso. Si la sucursal cambia de
  coordenadas, los QR activos siguen con las viejas hasta que se genera uno nuevo."""

import datetime as dt
import math

from mysql.connector import ProgrammingError

from repositories import carga_repository as db
from services.carga_service import now_local

DIAS = 30
MINIMO_FICHADAS = 5
CERCA_M = 150
MUESTRA = 300
QR_DESACTUALIZADO_M = 30


def distancia_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _mediana(valores):
    orden = sorted(valores)
    medio = len(orden) // 2
    return orden[medio] if len(orden) % 2 else (orden[medio - 1] + orden[medio]) / 2


def contexto(sucursal):
    """Para el formulario de una sucursal: sugerencia desde las fichadas, muestra de puntos y QR activos."""
    sucursal_id = int(sucursal["id"])
    desde = now_local().date() - dt.timedelta(days=DIAS)
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, """SELECT m.lat, m.lon, m.accion FROM asistencia_marcas m JOIN empleados e ON e.id = m.empleado_id
                                  WHERE e.sucursal_id = %s AND m.fecha >= %s AND m.lat IS NOT NULL AND m.lon IS NOT NULL
                                  ORDER BY m.id DESC LIMIT 3000""", (sucursal_id, desde))
        try:
            qrs = db.all_rows(c, """SELECT id, geo_lat, geo_lon, tolerancia_m, fecha, expira_at FROM qr_puerta_historial
                                    WHERE sucursal_id = %s AND activo = 1 AND expira_at >= %s
                                    ORDER BY fecha DESC, id DESC LIMIT 20""", (sucursal_id, now_local()))
        except ProgrammingError:  # instalaciones viejas sin la columna activo
            qrs = []
    puntos = [(float(f["lat"]), float(f["lon"]), f["accion"]) for f in filas]
    sugerencia = None
    if len(puntos) >= MINIMO_FICHADAS:
        lat, lon = _mediana([p[0] for p in puntos]), _mediana([p[1] for p in puntos])
        distancias = [distancia_m(lat, lon, p[0], p[1]) for p in puntos]
        sugerencia = dict(lat=round(lat, 7), lon=round(lon, 7), fichadas=len(puntos), dias=DIAS,
                          mitad_m=round(_mediana(distancias)), cerca=sum(1 for d in distancias if d <= CERCA_M), cerca_m=CERCA_M)
    actual = (float(sucursal["latitud"]), float(sucursal["longitud"])) \
        if sucursal.get("latitud") is not None and sucursal.get("longitud") is not None else None
    if sugerencia and actual:
        sugerencia["distancia_actual_m"] = round(distancia_m(actual[0], actual[1], sugerencia["lat"], sugerencia["lon"]))
    lista_qr = []
    for q in qrs:
        lat, lon = float(q["geo_lat"]), float(q["geo_lon"])
        lejos = round(distancia_m(actual[0], actual[1], lat, lon)) if actual else None
        lista_qr.append(dict(id=int(q["id"]), lat=lat, lon=lon, tolerancia=int(q["tolerancia_m"]), fecha=q["fecha"],
                             expira=q["expira_at"], distancia_m=lejos,
                             desactualizado=lejos is not None and lejos > QR_DESACTUALIZADO_M))
    return dict(sugerencia=sugerencia, qrs=lista_qr,
                mapa=dict(sugerencia=sugerencia, puntos=[[round(p[0], 6), round(p[1], 6), p[2]] for p in puntos[:MUESTRA]],
                          qrs=[dict(lat=q["lat"], lon=q["lon"], tolerancia=q["tolerancia"], desactualizado=q["desactualizado"])
                               for q in lista_qr]))
