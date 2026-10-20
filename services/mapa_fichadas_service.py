"""Mapa de fichadas: donde ficho cada empleado contra el punto y el radio permitido (solo lectura, solo panel).

Lee asistencia_marcas (lat, lon, gps_ok, distancia, tolerancia, punto de referencia de la validacion y, desde el
contrato 1.54.0, la calidad de la ubicacion: precision, GPS simulado y antiguedad) y las sucursales (coordenadas y radio
permitido). No guarda nada.

Alertas (para analizar, no cambian la validacion): fuera de radio, GPS simulado y posicion vieja (mas de POSICION_VIEJA_S
segundos al fichar)."""

import datetime as dt

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

MAX_DIAS = 31
MAX_PUNTOS = 3000
POSICION_VIEJA_S = 120
VISTAS = ("todas", "fuera", "alertas")


def _fecha(valor, nombre):
    try:
        return dt.date.fromisoformat(str(valor).strip()[:10])
    except (TypeError, ValueError):
        raise Error(f"{nombre}: fecha inválida.") from None


def _numero(valor):
    return float(valor) if valor is not None else None


def periodo(fuente):
    """(desde, hasta) del pedido; por defecto los ultimos 7 dias."""
    hoy = now_local().date()
    desde = _fecha(fuente.get("desde"), "Desde") if fuente.get("desde") else hoy - dt.timedelta(days=6)
    hasta = _fecha(fuente.get("hasta"), "Hasta") if fuente.get("hasta") else hoy
    if desde > hasta:
        raise Error("'Desde' no puede ser posterior a 'Hasta'.")
    if (hasta - desde).days + 1 > MAX_DIAS:
        raise Error(f"El período máximo es de {MAX_DIAS} días.")
    return desde, hasta


def fichadas(empresa_id, desde, hasta, filtros=None):
    """Fichadas del periodo con su ubicacion y las referencias (sucursales y puntos de validacion)."""
    filtros = filtros or {}
    donde, args = ["m.empresa_id = %s", "m.fecha BETWEEN %s AND %s", "e.empresa_id = %s"], [empresa_id, desde, hasta, empresa_id]
    for clave, columna in (("sucursal_id", "e.sucursal_id"), ("empleado_id", "m.empleado_id")):
        valor = str(filtros.get(clave) or "")
        if valor.isdigit():
            donde.append(f"{columna} = %s")
            args.append(int(valor))
    if filtros.get("accion") in ("ingreso", "egreso"):
        donde.append("m.accion = %s")
        args.append(filtros["accion"])
    alerta = f"(m.gps_ok = 0 OR m.gps_simulada = 1 OR m.gps_edad_s > {POSICION_VIEJA_S})"
    if filtros.get("ver") == "fuera":
        donde.append("m.gps_ok = 0")
    elif filtros.get("ver") == "alertas":
        donde.append(alerta)
    where = " AND ".join(donde)
    with db.transaction(read_only=True) as c:
        totales = db.one(c, f"""SELECT COUNT(*) AS total,
                                       SUM(m.lat IS NOT NULL AND m.lon IS NOT NULL) AS con_ubicacion,
                                       SUM(m.gps_ok = 0) AS fuera, SUM(m.gps_ok = 1) AS dentro,
                                       SUM(m.gps_simulada = 1) AS simuladas, SUM(m.gps_edad_s > {POSICION_VIEJA_S}) AS viejas,
                                       SUM(m.gps_precision_m IS NOT NULL) AS con_precision
                                FROM asistencia_marcas m JOIN empleados e ON e.id = m.empleado_id WHERE {where}""", tuple(args))
        filas = db.all_rows(c, f"""SELECT m.id, m.empleado_id, m.fecha, m.hora, m.accion, m.metodo, m.lat, m.lon, m.gps_ok,
                                          m.gps_distancia_m, m.gps_tolerancia_m, m.gps_ref_lat, m.gps_ref_lon,
                                          m.gps_precision_m, m.gps_simulada, m.gps_edad_s,
                                          e.apellido, e.nombre, e.legajo, su.nombre AS sucursal_nombre
                                   FROM asistencia_marcas m JOIN empleados e ON e.id = m.empleado_id
                                   LEFT JOIN sucursales su ON su.id = e.sucursal_id
                                   WHERE {where} AND m.lat IS NOT NULL AND m.lon IS NOT NULL
                                   ORDER BY {alerta} DESC, m.fecha DESC, m.hora DESC, m.id DESC
                                   LIMIT %s""", (*args, MAX_PUNTOS + 1))
        sucursales = db.all_rows(c, """SELECT id, nombre, latitud, longitud, radio_permitido_m FROM sucursales
                                       WHERE empresa_id = %s AND latitud IS NOT NULL AND longitud IS NOT NULL
                                       ORDER BY nombre""", (empresa_id,))
    recortado = len(filas) > MAX_PUNTOS
    filas = filas[:MAX_PUNTOS]
    puntos = [dict(
        id=int(f["id"]), lat=_numero(f["lat"]), lon=_numero(f["lon"]),
        estado="fuera" if f["gps_ok"] == 0 else ("dentro" if f["gps_ok"] == 1 else "sin_validar"),
        empleado=f"{f['apellido']}, {f['nombre']}", legajo=f["legajo"], sucursal=f["sucursal_nombre"],
        fecha=f["fecha"].strftime("%d/%m/%Y"), hora=_hhmm(f["hora"]),
        accion=f["accion"], metodo=f["metodo"],
        distancia=round(float(f["gps_distancia_m"])) if f["gps_distancia_m"] is not None else None,
        tolerancia=round(float(f["gps_tolerancia_m"])) if f["gps_tolerancia_m"] is not None else None,
        ref=[_numero(f["gps_ref_lat"]), _numero(f["gps_ref_lon"])] if f["gps_ref_lat"] is not None and f["gps_ref_lon"] is not None else None,
        precision=round(float(f["gps_precision_m"])) if f["gps_precision_m"] is not None else None,
        simulada=bool(f["gps_simulada"]) if f["gps_simulada"] is not None else None,
        edad=int(f["gps_edad_s"]) if f["gps_edad_s"] is not None else None,
    ) for f in filas]
    for p in puntos:
        p["distancia_txt"] = metros(p["distancia"])
        p["alertas"] = []
        if p["estado"] == "fuera":
            p["alertas"].append("Fuera del radio")
        if p["simulada"]:
            p["alertas"].append("GPS simulado")
        if p["edad"] is not None and p["edad"] > POSICION_VIEJA_S:
            p["alertas"].append(f"Posición de hace {_antiguedad(p['edad'])}")
    referencias = [dict(nombre=s["nombre"], lat=_numero(s["latitud"]), lon=_numero(s["longitud"]),
                        radio=int(s["radio_permitido_m"]) if s["radio_permitido_m"] else None, tipo="sucursal")
                   for s in sucursales]
    vistos = {(round(r["lat"], 5), round(r["lon"], 5)) for r in referencias}
    for p in puntos:  # puntos de validacion (QR de puerta) que no son una sucursal
        if p["ref"] and (round(p["ref"][0], 5), round(p["ref"][1], 5)) not in vistos:
            vistos.add((round(p["ref"][0], 5), round(p["ref"][1], 5)))
            referencias.append(dict(nombre="Punto de validación", lat=p["ref"][0], lon=p["ref"][1], radio=p["tolerancia"], tipo="qr"))
    total = int(totales["total"] or 0)
    con_ubicacion = int(totales["con_ubicacion"] or 0)
    return dict(desde=desde, hasta=hasta, puntos=puntos, referencias=referencias, recortado=recortado,
                totales=dict(total=total, con_ubicacion=con_ubicacion, sin_ubicacion=total - con_ubicacion,
                             fuera=int(totales["fuera"] or 0), dentro=int(totales["dentro"] or 0),
                             simuladas=int(totales["simuladas"] or 0), viejas=int(totales["viejas"] or 0),
                             con_precision=int(totales["con_precision"] or 0)))


def metros(valor):
    """137 -> '137 m'; 54523 -> '54,5 km' (para leer de un vistazo)."""
    if valor is None:
        return None
    if valor < 1000:
        return f"{int(valor)} m"
    km = valor / 1000
    return (f"{km:.1f}" if km < 100 else f"{km:.0f}").replace(".", ",") + " km"


def _antiguedad(segundos):
    return f"{segundos // 60} min" if segundos >= 60 else f"{segundos} s"


def _hhmm(valor):
    """'8:05:00', '08:05' o un TIME de MySQL -> '08:05'."""
    texto = str(valor or "")
    if ":" not in texto:
        return texto
    h, m = texto.split(":")[:2]
    return f"{int(h):02d}:{int(m):02d}"
