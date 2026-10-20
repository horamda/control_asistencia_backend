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


# --- Correccion de fichadas validadas contra una ubicacion anterior ----------------------------------------------

MAX_DIAS_CORRECCION = 366


class CorreccionError(ValueError):
    pass


def _refs_anteriores(c, sucursal_id):
    """Ubicaciones contra las que se validaron fichadas de la sucursal: las de todos sus QR (activos o no)."""
    try:
        filas = db.all_rows(c, "SELECT DISTINCT ROUND(geo_lat, 5) AS lat, ROUND(geo_lon, 5) AS lon FROM qr_puerta_historial"
                               " WHERE sucursal_id = %s", (int(sucursal_id),))
    except ProgrammingError:
        filas = []
    return [(float(f["lat"]), float(f["lon"])) for f in filas if f["lat"] is not None and f["lon"] is not None]


def _marcas_a_corregir(c, sucursal, desde, hasta, lock=False):
    actual = (float(sucursal["latitud"]), float(sucursal["longitud"]))
    refs = [r for r in _refs_anteriores(c, sucursal["id"]) if distancia_m(r[0], r[1], *actual) > 1]
    if not refs:
        return []
    condicion = " OR ".join(["(ROUND(m.gps_ref_lat, 5) = %s AND ROUND(m.gps_ref_lon, 5) = %s)"] * len(refs))
    args = [v for r in refs for v in r]
    return db.all_rows(c, f"""SELECT m.id, m.empresa_id, m.empleado_id, m.asistencia_id, m.fecha, m.hora, m.accion, m.lat, m.lon,
                                     m.gps_ok, m.gps_distancia_m, m.gps_tolerancia_m, m.gps_ref_lat, m.gps_ref_lon
                              FROM asistencia_marcas m
                              WHERE m.empresa_id = %s AND m.fecha BETWEEN %s AND %s AND m.lat IS NOT NULL AND m.lon IS NOT NULL
                                AND ({condicion}) ORDER BY m.id""" + (" FOR UPDATE" if lock else ""),
                       (int(sucursal["empresa_id"]), desde, hasta, *args))


def _nuevo(marca, sucursal):
    distancia = round(distancia_m(float(marca["lat"]), float(marca["lon"]),
                                  float(sucursal["latitud"]), float(sucursal["longitud"])), 2)
    tolerancia = float(sucursal["radio_permitido_m"] or marca["gps_tolerancia_m"] or 0)
    return distancia, tolerancia, int(distancia <= tolerancia)


def _periodo(desde, hasta):
    try:
        desde, hasta = dt.date.fromisoformat(str(desde)[:10]), dt.date.fromisoformat(str(hasta)[:10])
    except ValueError:
        raise CorreccionError("Fechas inválidas.") from None
    if desde > hasta:
        raise CorreccionError("'Desde' no puede ser posterior a 'Hasta'.")
    if (hasta - desde).days + 1 > MAX_DIAS_CORRECCION:
        raise CorreccionError(f"El período máximo es de {MAX_DIAS_CORRECCION} días.")
    return desde, hasta


def vista_correccion(sucursal, desde, hasta):
    """Cuantas fichadas se validaron contra una ubicacion anterior y como quedarian con la actual (no cambia nada)."""
    if sucursal.get("latitud") is None or sucursal.get("longitud") is None:
        return None
    desde, hasta = _periodo(desde, hasta)
    with db.transaction(read_only=True) as c:
        marcas = _marcas_a_corregir(c, sucursal, desde, hasta)
    nuevos = [_nuevo(m, sucursal) for m in marcas]
    return dict(desde=desde, hasta=hasta, total=len(marcas),
                fuera_antes=sum(1 for m in marcas if m["gps_ok"] == 0),
                dentro_despues=sum(1 for n in nuevos if n[2]),
                pasan_a_dentro=sum(1 for m, n in zip(marcas, nuevos) if m["gps_ok"] == 0 and n[2]),
                quedan_fuera=sum(1 for n in nuevos if not n[2]))


def corregir(who, sucursal, desde, hasta, motivo):
    """Recalcula distancia y "dentro del radio" de esas fichadas con la ubicacion actual de la sucursal, guardando los
    valores anteriores (asistencia_marcas_geo_correcciones). Actualiza el resumen del dia y anula el evento de
    seguridad de las que pasan a quedar dentro."""
    import uuid

    motivo = " ".join(str(motivo or "").split())[:255]
    if not motivo:
        raise CorreccionError("Indicá el motivo de la corrección.")
    if sucursal.get("latitud") is None or sucursal.get("longitud") is None:
        raise CorreccionError("La sucursal no tiene ubicación cargada.")
    desde, hasta = _periodo(desde, hasta)
    lote = uuid.uuid4().hex
    ahora = now_local().replace(microsecond=0)
    ref = (round(float(sucursal["latitud"]), 7), round(float(sucursal["longitud"]), 7))
    resumen = dict(corregidas=0, pasan_a_dentro=0, eventos_anulados=0, lote=lote)
    with db.transaction() as c:
        for m in _marcas_a_corregir(c, sucursal, desde, hasta, lock=True):
            distancia, tolerancia, ok = _nuevo(m, sucursal)
            evento_id = None
            if m["gps_ok"] == 0 and ok:
                evento = db.one(c, """SELECT id FROM eventos_seguridad WHERE empleado_id = %s AND fecha_operacion = %s
                                      AND hora_operacion = %s AND alerta_fraude = 1 ORDER BY id LIMIT 1 FOR UPDATE""",
                                (m["empleado_id"], m["fecha"], m["hora"]))
                if evento:
                    evento_id = evento["id"]
                    c.execute("""UPDATE eventos_seguridad SET alerta_fraude = 0,
                                 payload_json = JSON_SET(COALESCE(payload_json, JSON_OBJECT()), '$.anulado',
                                                         'Ubicacion de la sucursal corregida', '$.anulado_lote', %s)
                                 WHERE id = %s""", (lote, evento_id))
                    resumen["eventos_anulados"] += 1
                resumen["pasan_a_dentro"] += 1
            db.insert(c, "asistencia_marcas_geo_correcciones", dict(
                lote=lote, marca_id=m["id"], empresa_id=m["empresa_id"], sucursal_id=int(sucursal["id"]),
                antes_gps_ok=m["gps_ok"], antes_distancia_m=m["gps_distancia_m"], antes_tolerancia_m=m["gps_tolerancia_m"],
                antes_ref_lat=m["gps_ref_lat"], antes_ref_lon=m["gps_ref_lon"], despues_gps_ok=ok,
                despues_distancia_m=distancia, despues_tolerancia_m=tolerancia, despues_ref_lat=ref[0],
                despues_ref_lon=ref[1], evento_anulado_id=evento_id, motivo=motivo, usuario_id=who.get("user_id"),
                creado_at=ahora))
            nota = (f"geo corregido {ahora:%d/%m/%Y}: gps_ok={ok};dist_m={distancia};tol_m={tolerancia:g};"
                    f"ref={ref[0]},{ref[1]}")
            c.execute("""UPDATE asistencia_marcas SET gps_ok = %s, gps_distancia_m = %s, gps_tolerancia_m = %s,
                         gps_ref_lat = %s, gps_ref_lon = %s, observaciones = CONCAT_WS(' | ', observaciones, %s)
                         WHERE id = %s""", (ok, distancia, tolerancia, ref[0], ref[1], nota, m["id"]))
            if m["asistencia_id"]:
                lado, hora = ("entrada", "hora_entrada") if m["accion"] == "ingreso" else ("salida", "hora_salida")
                c.execute(f"""UPDATE asistencias SET gps_ok_{lado} = %s, gps_distancia_{lado}_m = %s,
                              gps_tolerancia_{lado}_m = %s, gps_ref_lat_{lado} = %s, gps_ref_lon_{lado} = %s
                              WHERE id = %s AND {hora} = %s""",
                          (ok, distancia, tolerancia, ref[0], ref[1], m["asistencia_id"], m["hora"]))
            resumen["corregidas"] += 1
    return resumen


def correcciones(sucursal_id, limite=10):
    """Lotes de correccion de la sucursal (para el historial del formulario)."""
    with db.transaction(read_only=True) as c:
        try:
            return db.all_rows(c, """SELECT k.lote, MIN(k.creado_at) AS creado_at, COUNT(*) AS marcas,
                                            SUM(k.antes_gps_ok = 0 AND k.despues_gps_ok = 1) AS pasaron_a_dentro,
                                            SUM(k.evento_anulado_id IS NOT NULL) AS eventos, MIN(k.motivo) AS motivo,
                                            MIN(u.usuario) AS usuario
                                     FROM asistencia_marcas_geo_correcciones k LEFT JOIN usuarios u ON u.id = k.usuario_id
                                     WHERE k.sucursal_id = %s GROUP BY k.lote ORDER BY MIN(k.id) DESC LIMIT %s""",
                               (int(sucursal_id), limite))
        except ProgrammingError:
            return []
