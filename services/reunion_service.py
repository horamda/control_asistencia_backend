"""Reuniones: recurrencia, sedes por sucursal, convocados, QR fijo/dinamico, asistencia y estadisticas.

Una reunion puede hacerse en varias sucursales (sedes), cada una con lugar y hora propios
opcionales. Cada empleado va a la sede de su sucursal; sin sedes hay una sola sesion para todos
(sucursal_id = 0). Cada fecha de cada sede se guarda en reunion_ocurrencias con su horario
congelado: editar la reunion no altera el historial. Al terminar la ventana de registro, el
cierre (scheduler) marca ausentes a los convocados sin registro y justifica vacaciones/francos."""

import calendar
import datetime as dt
import logging
from urllib.parse import parse_qs, urlparse

import jwt
from mysql.connector import IntegrityError

from repositories import carga_repository as db
from services import feriado_service
from services.carga_service import CargaError as Error, now_local
from utils.jwt import _get_secret

logger = logging.getLogger(__name__)

FRECUENCIAS = ("diaria", "semanal", "mensual")
QR_MODOS = ("fijo", "dinamico", "ambos")
ESTADOS = ("presente", "tarde", "ausente", "justificado")
QR_PREFIX = "fichaya://reunion?t="
QR_TIPO = "reunion_qr"
QR_DINAMICO_TTL = 45
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
SEMANAS = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "último"}
MAX_RANGO_DIAS = 366
SIN_SEDE = 0
FERIADO_ACCIONES = ("posponer", "omitir", "mantener")
MAX_POSPONER_DIAS = 14


# --- Utilidades ----------------------------------------------------------------------

def _time(value):
    if isinstance(value, dt.time):
        return value
    if isinstance(value, dt.timedelta):
        minutes = int(value.total_seconds() // 60)
        return dt.time(minutes // 60, minutes % 60)
    hh, mm = str(value).split(":")[:2]
    return dt.time(int(hh), int(mm))


def _date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _dias(value):
    if not value:
        return []
    return sorted({int(x) for x in str(value).split(",") if str(x).strip().isdigit() and 0 <= int(x) <= 6})


def _hhmm(value):
    return value.strftime("%H:%M") if value else None


def _iso(value):
    """Fechas ISO; fecha y hora con la zona de Argentina, como el resto de la API mobile."""
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds") + "-03:00"
    return value.isoformat() if value else None


def _int(value, nombre, minimo, maximo, default=None):
    raw = str(value if value is not None else "").strip()
    if raw == "":
        if default is None:
            raise Error(f"{nombre}: campo obligatorio.")
        return default
    if not raw.lstrip("-").isdigit() or not minimo <= int(raw) <= maximo:
        raise Error(f"{nombre}: use un entero entre {minimo} y {maximo}.")
    return int(raw)


def _marcas(valores):
    return ", ".join(["%s"] * len(valores)) or "NULL"


def pct(parte, total):
    return round(parte * 100.0 / total, 1) if total else None


# --- Recurrencia ---------------------------------------------------------------------

def _ocurre_regla(r, fecha):
    """True si la regla de recurrencia de r cae en la fecha (sin mirar feriados)."""
    if fecha < _date(r["fecha_inicio"]) or (r.get("fecha_fin") and fecha > _date(r["fecha_fin"])):
        return False
    dias = _dias(r.get("dias_semana"))
    if r["frecuencia"] in ("diaria", "semanal"):
        return fecha.weekday() in dias
    ultimo = calendar.monthrange(fecha.year, fecha.month)[1]
    if r.get("mensual_tipo") == "semana":
        if not dias or fecha.weekday() != dias[0]:
            return False
        semana = int(r.get("semana_mes") or 1)
        if semana == 5:
            return fecha.day + 7 > ultimo
        return (fecha.day - 1) // 7 + 1 == semana
    return fecha.day == min(int(r.get("dia_mes") or 1), ultimo)


def _dia_habil_siguiente(fecha, feriados):
    dia = fecha + dt.timedelta(days=1)
    for _ in range(MAX_POSPONER_DIAS):
        if dia.weekday() < 5 and dia not in feriados:
            return dia
        dia += dt.timedelta(days=1)
    return None


def calendario(r, desde, hasta):
    """Fechas de r entre desde y hasta aplicando los feriados de su sede (r["_feriados"]).

    Cada item: fecha (efectiva), original (si se pospuso), feriado (nombre) y omitida. Si cae en
    feriado se pospone al siguiente dia habil, se omite o se mantiene segun r["feriado_accion"]; si el
    dia habil siguiente ya tiene esa misma reunion, no se duplica: se omite."""
    if (hasta - desde).days > MAX_RANGO_DIAS:
        hasta = desde + dt.timedelta(days=MAX_RANGO_DIAS)
    feriados = r.get("_feriados") or {}
    accion = r.get("feriado_accion") or "posponer"
    # Una fecha anterior al rango puede posponerse hacia dentro del rango.
    inicio = desde - dt.timedelta(days=MAX_POSPONER_DIAS if feriados else 0)
    reglas = []
    dia = inicio
    while dia <= hasta:
        if _ocurre_regla(r, dia):
            reglas.append(dia)
        dia += dt.timedelta(days=1)
    regulares = {d for d in reglas if d not in feriados}
    salida = []
    for dia in reglas:
        nombre = feriados.get(dia)
        if nombre is None or accion == "mantener":
            item = dict(fecha=dia, original=None, feriado=nombre, omitida=False)
        else:
            nueva = _dia_habil_siguiente(dia, feriados) if accion == "posponer" else None
            if nueva and nueva not in regulares and (not r.get("fecha_fin") or nueva <= _date(r["fecha_fin"])):
                item = dict(fecha=nueva, original=dia, feriado=nombre, omitida=False)
            else:
                item = dict(fecha=dia, original=None, feriado=nombre, omitida=True)
        if desde <= item["fecha"] <= hasta:
            salida.append(item)
    salida.sort(key=lambda x: x["fecha"])
    return salida


def fechas(r, desde, hasta):
    """Fechas efectivas en que se hace la reunion (con feriados aplicados)."""
    vistas = set()
    for item in calendario(r, desde, hasta):
        if not item["omitida"] and item["fecha"] not in vistas:
            vistas.add(item["fecha"])
            yield item["fecha"]


def ocurre_en(r, fecha):
    """True si la reunion r (en su sede, con sus feriados) se hace en la fecha dada."""
    return fecha in set(fechas(r, fecha, fecha))


def info_fecha(r, fecha):
    """Item del calendario de esa fecha (efectiva u original omitida/pospuesta), o None."""
    for item in calendario(r, fecha - dt.timedelta(days=MAX_POSPONER_DIAS), fecha + dt.timedelta(days=MAX_POSPONER_DIAS)):
        if item["fecha"] == fecha or item["original"] == fecha:
            return item
    return None


def _causa(nombre):
    """'día no laborable', con el nombre (motivo del calendario) si lo tiene."""
    if not nombre or nombre == feriado_service.SIN_NOMBRE:
        return "día no laborable"
    return f"día no laborable ({nombre})"


def motivo_cambio(item):
    if not item or not item.get("feriado"):
        return None
    if item["omitida"]:
        return f"No se hace: {_causa(item['feriado'])}."
    if item["original"]:
        return (f"Pospuesta del {DIAS[item['original'].weekday()].lower()} {item['original'].strftime('%d/%m')}"
                f" por {_causa(item['feriado'])}.")
    return None


def proxima_fecha(r, desde=None, dias=MAX_RANGO_DIAS):
    desde = desde or now_local().date()
    return next(fechas(r, desde, desde + dt.timedelta(days=dias)), None)


def horarios(r, fecha):
    """Momentos de la ocurrencia: inicio, fin y ventana de registro (r con la hora de su sede)."""
    inicio = dt.datetime.combine(fecha, _time(r["hora_inicio"]))
    fin = inicio + dt.timedelta(minutes=int(r["duracion_min"]))
    cierre = r.get("cierre_despues_min")
    return dict(
        inicio=inicio,
        fin=fin,
        ventana_desde=inicio - dt.timedelta(minutes=int(r["tolerancia_antes_min"])),
        ventana_hasta=fin if cierre in (None, "") else inicio + dt.timedelta(minutes=int(cierre)),
        tarde_desde=inicio + dt.timedelta(minutes=int(r["tarde_despues_min"])),
    )


def describir(r, hora=None):
    hora = hora or _hhmm(_time(r["hora_inicio"]))
    dias = _dias(r.get("dias_semana"))
    if r["frecuencia"] == "diaria":
        cuando = "Todos los días" if len(dias) == 7 else (
            "De lunes a viernes" if dias == [0, 1, 2, 3, 4] else "Diaria: " + ", ".join(DIAS[d].lower() for d in dias))
    elif r["frecuencia"] == "semanal":
        nombres = [DIAS[d].lower() for d in dias]
        cuando = "Todos los " + (" y ".join([", ".join(nombres[:-1]), nombres[-1]]) if len(nombres) > 1 else nombres[0])
        cuando = cuando.replace("todos los sábado", "todos los sábados").replace("todos los domingo", "todos los domingos")
    elif r.get("mensual_tipo") == "semana":
        cuando = f"El {SEMANAS.get(int(r.get('semana_mes') or 1), '')} {DIAS[dias[0]].lower() if dias else ''} de cada mes"
    else:
        cuando = f"El día {int(r.get('dia_mes') or 1)} de cada mes"
    return f"{cuando} a las {hora} ({int(r['duracion_min'])} min)"


# --- Sedes (sucursales) -----------------------------------------------------------------

def sedes(c, reunion_id):
    return db.all_rows(
        c, """SELECT rs.sucursal_id, rs.lugar, rs.hora_inicio, su.nombre AS sucursal_nombre
              FROM reunion_sedes rs LEFT JOIN sucursales su ON su.id = rs.sucursal_id
              WHERE rs.reunion_id = %s ORDER BY su.nombre, rs.sucursal_id""", (reunion_id,))


def en_sede(r, sede=None):
    """La reunion tal como se hace en una sede: hora y lugar propios si los tiene."""
    if not sede or not sede.get("sucursal_id"):
        return dict(r, sucursal_id=SIN_SEDE, sucursal_nombre=None)
    return dict(r, sucursal_id=int(sede["sucursal_id"]), sucursal_nombre=sede.get("sucursal_nombre"),
                hora_inicio=sede.get("hora_inicio") or r["hora_inicio"], lugar=sede.get("lugar") or r.get("lugar"))


def sedes_efectivas(c, r, lista=None, feriados=None):
    """La reunion en cada sede, con los feriados que aplican a esa sucursal (r["_feriados"])."""
    lista = sedes(c, r["id"]) if lista is None else lista
    feriados = feriado_service.mapa(c, r["empresa_id"]) if feriados is None else feriados
    salida = [en_sede(r, s) for s in lista] or [en_sede(r)]
    for item in salida:
        item["_feriados"] = feriado_service.de_sucursal(feriados, item["sucursal_id"])
    return salida


def sede(c, r, sucursal_id):
    """La reunion en la sede indicada (0 = sesion unica). Error si no se hace en esa sucursal."""
    for item in sedes_efectivas(c, r):
        if item["sucursal_id"] == int(sucursal_id or 0):
            return item
    raise Error("La reunión no se hace en esa sucursal.", 404)


def sede_de_empleado(c, r, empleado):
    for item in sedes_efectivas(c, r):
        if item["sucursal_id"] in (SIN_SEDE, empleado.get("sucursal_id")):
            return item
    return None


# --- Convocados ----------------------------------------------------------------------

# Una regla sin empleado aplica por sector/puesto; sector y puesto NULL = toda la empresa.
# Cuenta el puesto principal y los puestos adicionales activos (empleado_puestos).
_REGLA_EMPLEADO = """(
    p.empleado_id = e.id
    OR (p.empleado_id IS NULL AND (
        ((p.sector_id IS NULL OR p.sector_id = e.sector_id) AND (p.puesto_id IS NULL OR p.puesto_id = e.puesto_id))
        OR EXISTS (SELECT 1 FROM empleado_puestos ep WHERE ep.empleado_id = e.id AND ep.activo = 1
                   AND (p.sector_id IS NULL OR p.sector_id = ep.sector_id)
                   AND (p.puesto_id IS NULL OR p.puesto_id = ep.puesto_id))
    ))
)"""

# Con sedes, solo cuentan los empleados de esas sucursales.
_SEDE_EMPLEADO = """(NOT EXISTS (SELECT 1 FROM reunion_sedes rs WHERE rs.reunion_id = {rid})
    OR e.sucursal_id IN (SELECT rs.sucursal_id FROM reunion_sedes rs WHERE rs.reunion_id = {rid}))"""


def convocados(c, reunion, sucursal_id=None):
    sql = f"""SELECT e.id, e.apellido, e.nombre, e.legajo, e.sucursal_id, s.nombre AS sector_nombre,
                     su.nombre AS sucursal_nombre
              FROM empleados e LEFT JOIN sectores s ON s.id = e.sector_id
              LEFT JOIN sucursales su ON su.id = e.sucursal_id
              WHERE e.empresa_id = %s AND e.activo = 1
                AND EXISTS (SELECT 1 FROM reunion_participantes p WHERE p.reunion_id = %s AND {_REGLA_EMPLEADO})
                AND {_SEDE_EMPLEADO.format(rid="%s")}"""
    args = [reunion["empresa_id"], reunion["id"], reunion["id"], reunion["id"]]
    if sucursal_id:
        sql += " AND e.sucursal_id = %s"
        args.append(int(sucursal_id))
    return db.all_rows(c, sql + " ORDER BY e.apellido, e.nombre", tuple(args))


def contar_convocados(c, empresa_id):
    rows = db.all_rows(
        c,
        f"""SELECT r.id, COUNT(e.id) AS n FROM reuniones r
            JOIN empleados e ON e.empresa_id = r.empresa_id AND e.activo = 1
            WHERE r.empresa_id = %s
              AND EXISTS (SELECT 1 FROM reunion_participantes p WHERE p.reunion_id = r.id AND {_REGLA_EMPLEADO})
              AND {_SEDE_EMPLEADO.format(rid="r.id")}
            GROUP BY r.id""",
        (empresa_id,),
    )
    return {row["id"]: int(row["n"]) for row in rows}


def reuniones_de_empleado(c, empleado, reunion_id=None, solo_activas=True):
    sql = f"""SELECT r.* FROM reuniones r JOIN empleados e ON e.id = %s
              WHERE r.empresa_id = e.empresa_id
                AND EXISTS (SELECT 1 FROM reunion_participantes p WHERE p.reunion_id = r.id AND {_REGLA_EMPLEADO})
                AND {_SEDE_EMPLEADO.format(rid="r.id")}"""
    args = [empleado["id"]]
    if solo_activas:
        sql += " AND r.activa = 1"
    if reunion_id:
        sql += " AND r.id = %s"
        args.append(int(reunion_id))
    return db.all_rows(c, sql + " ORDER BY r.hora_inicio, r.nombre", tuple(args))


def _de_empleado_en_sede(c, empleado, **kw):
    """Reuniones del empleado ya ubicadas en su sede (hora y lugar efectivos). Sedes y dias no laborables en
    una consulta para todas (sin una por reunion)."""
    reuniones = reuniones_de_empleado(c, empleado, **kw)
    if not reuniones:
        return []
    ids = [r["id"] for r in reuniones]
    sedes_de = {}
    for fila in db.all_rows(c, f"""SELECT rs.reunion_id, rs.sucursal_id, rs.lugar, rs.hora_inicio, su.nombre AS sucursal_nombre
                                   FROM reunion_sedes rs LEFT JOIN sucursales su ON su.id = rs.sucursal_id
                                   WHERE rs.reunion_id IN ({_marcas(ids)}) ORDER BY su.nombre, rs.sucursal_id""",
                            tuple(ids)):
        sedes_de.setdefault(fila["reunion_id"], []).append(fila)
    feriados = feriado_service.mapa(c, empleado["empresa_id"])
    salida = []
    for r in reuniones:
        item = next((x for x in sedes_efectivas(c, r, sedes_de.get(r["id"], []), feriados)
                     if x["sucursal_id"] in (SIN_SEDE, empleado.get("sucursal_id"))), None)
        if item:
            salida.append(item)
    return salida


# --- Ocurrencias -----------------------------------------------------------------------

def ocurrencia(c, r, fecha, crear=True, lock=False):
    """Fila de la ocurrencia de r (reunion en una sede) en la fecha; la crea con el horario actual."""
    sql = ("SELECT * FROM reunion_ocurrencias WHERE reunion_id = %s AND sucursal_id = %s AND fecha = %s"
           + (" FOR UPDATE" if lock else ""))
    args = (r["id"], r["sucursal_id"], fecha)
    row = db.one(c, sql, args)
    if row or not crear:
        return row
    h = horarios(r, fecha)
    item = info_fecha(r, fecha) if r.get("_feriados") else None
    original = item["original"] if item and item["fecha"] == fecha else None
    c.execute(
        """INSERT IGNORE INTO reunion_ocurrencias
           (empresa_id, reunion_id, sucursal_id, fecha, fecha_original, inicio, fin, ventana_desde, ventana_hasta,
            tarde_desde, estado, motivo_cambio)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'programada',%s)""",
        (r["empresa_id"], r["id"], r["sucursal_id"], fecha, original, h["inicio"], h["fin"], h["ventana_desde"],
         h["ventana_hasta"], h["tarde_desde"], motivo_cambio(item) if original else None),
    )
    return db.one(c, sql, args)


def _guardadas(c, desde, hasta, empresa_id=None):
    """Ocurrencias ya creadas en el rango: {(reunion, sede, fecha): fila}. Su horario manda sobre la
    regla (p. ej. una fecha reprogramada a mano)."""
    sql = "SELECT * FROM reunion_ocurrencias WHERE fecha BETWEEN %s AND %s"
    args = [desde, hasta]
    if empresa_id:
        sql += " AND empresa_id = %s"
        args.append(empresa_id)
    return {(o["reunion_id"], o["sucursal_id"], o["fecha"]): o for o in db.all_rows(c, sql, tuple(args))}


def _justificacion_automatica(c, empleado_ids, fecha, occ=None):
    """Motivo por empleado para justificar una ausencia: vacaciones, franco o haber asistido a otra
    reunion que se superpone en horario con esta ocurrencia (no puede estar en las dos)."""
    if not empleado_ids:
        return {}
    marcas = _marcas(empleado_ids)
    motivos = {}
    if occ:
        for row in db.all_rows(c, f"""SELECT a.empleado_id, r.nombre FROM reunion_asistencias a
                                       JOIN reunion_ocurrencias o ON o.id = a.ocurrencia_id
                                       JOIN reuniones r ON r.id = a.reunion_id
                                       WHERE a.empleado_id IN ({marcas}) AND a.fecha = %s AND a.estado IN ('presente','tarde')
                                         AND o.id <> %s AND o.estado <> 'cancelada' AND o.inicio < %s AND o.fin > %s""",
                               (*empleado_ids, fecha, occ["id"], occ["fin"], occ["inicio"])):
            motivos.setdefault(row["empleado_id"], f"Asistió a {row['nombre']} (superpuesta)")
    for row in db.all_rows(c, f"SELECT empleado_id FROM vacaciones WHERE empleado_id IN ({marcas})"
                              " AND fecha_desde <= %s AND fecha_hasta >= %s", (*empleado_ids, fecha, fecha)):
        motivos[row["empleado_id"]] = "Vacaciones"
    for row in db.all_rows(c, f"SELECT empleado_id FROM francos WHERE empleado_id IN ({marcas}) AND fecha = %s",
                           (*empleado_ids, fecha)):
        motivos.setdefault(row["empleado_id"], "Franco")
    return motivos


def cerrar_ocurrencias(*, ahora=None, dias_atras=7):
    """Cierra las ocurrencias (de cada sede) cuya ventana de registro termino. Idempotente."""
    ahora = ahora or now_local()
    desde = ahora.date() - dt.timedelta(days=dias_atras)
    with db.transaction(read_only=True) as c:
        reuniones = [item for r in db.all_rows(c, "SELECT * FROM reuniones WHERE activa = 1")
                     for item in sedes_efectivas(c, r)]
        guardadas = _guardadas(c, desde, ahora.date())
    resumen = dict(cerradas=0, ausentes=0, justificados=0, errores=0)
    for r in reuniones:
        creada = r.get("created_at")
        for fecha in fechas(r, desde, ahora.date()):
            h = guardadas.get((r["id"], r["sucursal_id"], fecha)) or horarios(r, fecha)
            if h["ventana_hasta"] > ahora or (creada and h["inicio"] < creada):
                continue
            try:
                with db.transaction() as c:
                    occ = ocurrencia(c, r, fecha, lock=True)
                    if occ["estado"] != "programada" or occ["ventana_hasta"] > ahora:
                        continue
                    lista = convocados(c, r, r["sucursal_id"])
                    registrados = {row["empleado_id"] for row in db.all_rows(
                        c, "SELECT empleado_id FROM reunion_asistencias WHERE ocurrencia_id = %s", (occ["id"],))}
                    faltan = [e["id"] for e in lista if e["id"] not in registrados]
                    motivos = _justificacion_automatica(c, faltan, fecha, occ)
                    for empleado_id in faltan:
                        motivo = motivos.get(empleado_id)
                        db.insert(c, "reunion_asistencias", dict(
                            empresa_id=r["empresa_id"], reunion_id=r["id"], sucursal_id=r["sucursal_id"],
                            ocurrencia_id=occ["id"], empleado_id=empleado_id, fecha=fecha,
                            estado="justificado" if motivo else "ausente", metodo="sistema",
                            observaciones=motivo, updated_at=ahora))
                        resumen["justificados" if motivo else "ausentes"] += 1
                    total = len(registrados | {e["id"] for e in lista})
                    c.execute("UPDATE reunion_ocurrencias SET estado='cerrada', convocados=%s, cerrada_at=%s WHERE id=%s",
                              (total, ahora, occ["id"]))
                    resumen["cerradas"] += 1
            except Exception:
                logger.exception("reunion_cierre_error", extra={"extra": {
                    "reunion_id": r["id"], "sucursal_id": r["sucursal_id"], "fecha": str(fecha)}})
                resumen["errores"] += 1
    if resumen["cerradas"] or resumen["errores"]:
        logger.info("reuniones_cierre", extra={"extra": resumen})
    return resumen


# --- QR ------------------------------------------------------------------------------

# Vencimiento fijo del QR impreso: el mismo contenido (y la misma imagen) cada vez que se muestra.
# Deja de valer al regenerarlo (qr_version), no por fecha.
QR_FIJO_EXP = 4102444800  # 2100-01-01 UTC


def _token(payload, ttl=None, *, exp=None):
    vence = exp if exp is not None else dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=ttl)
    return jwt.encode(dict(payload, type=QR_TIPO, exp=vence), _get_secret(), algorithm="HS256")


def qr_fijo(r):
    """QR impreso de la reunion en una sede (r = en_sede(...))."""
    return QR_PREFIX + _token({"rid": r["id"], "emp": r["empresa_id"], "s": int(r.get("sucursal_id") or 0),
                               "m": "fijo", "v": int(r["qr_version"])}, exp=QR_FIJO_EXP)


def qr_dinamico(r, fecha):
    return QR_PREFIX + _token({"rid": r["id"], "emp": r["empresa_id"], "s": int(r.get("sucursal_id") or 0),
                               "m": "dinamico", "f": fecha.isoformat()}, QR_DINAMICO_TTL)


def es_qr_reunion(contenido):
    return str(contenido or "").strip().startswith(QR_PREFIX.split("?")[0])


def _leer_qr(contenido):
    raw = str(contenido or "").strip()
    if not raw:
        raise Error("Escaneá el QR de la reunión.")
    token = raw
    if "://" in raw or raw.startswith("?") or "t=" in raw:
        valores = parse_qs(urlparse(raw).query).get("t") or parse_qs(raw.lstrip("?")).get("t")
        if not valores:
            raise Error("Este QR no es de una reunión.")
        token = valores[0]
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.ExpiredSignatureError:
        raise Error("El QR venció. Escaneá el código que se muestra ahora en pantalla.")
    except jwt.InvalidTokenError:
        raise Error("Este QR no es de una reunión o fue generado en otro sistema.")
    if payload.get("type") != QR_TIPO or not payload.get("rid"):
        raise Error("Este QR no es de una reunión.")
    return payload


# --- Registro de asistencia ------------------------------------------------------------

def _registro_dict(r, occ, row, ya_registrado):
    return dict(
        reunion_id=r["id"], reunion=r["nombre"], lugar=r.get("lugar"), sucursal_id=r["sucursal_id"],
        sucursal_nombre=r.get("sucursal_nombre"), fecha=_iso(occ["fecha"]), inicio=_hhmm(occ["inicio"]),
        fin=_hhmm(occ["fin"]), estado=row["estado"], registrado_at=_iso(row.get("registrado_at")),
        ya_registrado=ya_registrado,
    )


def registrar_qr(empleado, contenido, *, lat=None, lon=None, ahora=None):
    """Registra la asistencia del empleado autenticado a partir del QR escaneado."""
    ahora = ahora or now_local()
    payload = _leer_qr(contenido)
    if int(payload.get("emp") or 0) != int(empleado["empresa_id"]):
        raise Error("Este QR pertenece a otra empresa.", 403)
    with db.transaction() as c:
        base = db.one(c, "SELECT * FROM reuniones WHERE id = %s AND empresa_id = %s",
                      (payload["rid"], empleado["empresa_id"]))
        if not base or not base["activa"]:
            raise Error("La reunión no existe o está desactivada.", 404)
        modo = payload.get("m")
        if modo == "fijo" and (base["qr_modo"] == "dinamico" or int(payload.get("v") or 0) != int(base["qr_version"])):
            raise Error("Este QR impreso ya no es válido. Pedí el QR actualizado al organizador.", 409)
        if modo == "dinamico" and base["qr_modo"] == "fijo":
            raise Error("Esta reunión se registra con el QR impreso.", 409)
        if not reuniones_de_empleado(c, empleado, base["id"]):
            raise Error("No estás convocado a esta reunión.", 403)
        r = sede_de_empleado(c, base, empleado)
        if r is None:
            raise Error("No estás convocado a esta reunión.", 403)
        # QR anteriores a las sedes no traen "s": valen para la sede del empleado.
        if "s" in payload and int(payload["s"] or 0) != r["sucursal_id"]:
            otra = next((x for x in sedes_efectivas(c, base) if x["sucursal_id"] == int(payload["s"] or 0)), None)
            nombre = otra["sucursal_nombre"] if otra and otra.get("sucursal_nombre") else "otra sucursal"
            raise Error(f"Este QR es de la reunión en {nombre}. La tuya es en {r.get('sucursal_nombre') or 'tu sucursal'}.", 409)
        fecha = ahora.date()
        if modo == "dinamico" and payload.get("f") != fecha.isoformat():
            raise Error("El QR corresponde a otra fecha.", 409)
        existente = ocurrencia(c, r, fecha, crear=False, lock=True)
        if not existente and not ocurre_en(r, fecha):
            movida = info_fecha(r, fecha)
            if movida and movida["feriado"] and movida["original"] == fecha:
                raise Error(f"Hoy es {_causa(movida['feriado'])}: la reunión se pasó al "
                            f"{DIAS[movida['fecha'].weekday()].lower()} {movida['fecha'].strftime('%d/%m')}.", 409)
            if movida and movida["feriado"] and movida["omitida"]:
                raise Error(f"Hoy es {_causa(movida['feriado'])}: esta reunión no se hace.", 409)
            proxima = proxima_fecha(r, fecha)
            detalle = f" La próxima es el {proxima.strftime('%d/%m')}." if proxima else ""
            raise Error(f"Hoy no hay {r['nombre']}.{detalle}", 409)
        occ = existente or ocurrencia(c, r, fecha, lock=True)
        if occ["estado"] == "cancelada":
            raise Error("La reunión de hoy fue cancelada." + (f" Motivo: {occ['motivo_cancelacion']}" if occ.get("motivo_cancelacion") else ""), 409)
        previo = db.one(c, "SELECT * FROM reunion_asistencias WHERE ocurrencia_id = %s AND empleado_id = %s",
                        (occ["id"], empleado["id"]))
        if previo and previo["estado"] in ("presente", "tarde"):
            return _registro_dict(r, occ, previo, True)
        if ahora < occ["ventana_desde"]:
            raise Error(f"Todavía no se puede registrar. Se habilita a las {_hhmm(occ['ventana_desde'])}.", 409)
        if ahora > occ["ventana_hasta"] or occ["estado"] == "cerrada":
            raise Error(f"El registro cerró a las {_hhmm(occ['ventana_hasta'])}.", 409)
        estado = "tarde" if ahora > occ["tarde_desde"] else "presente"
        datos = dict(estado=estado, registrado_at=ahora, metodo=f"qr_{modo}", lat=lat, lon=lon, updated_at=ahora)
        # Si otra reunion superpuesta ya cerro y lo marco ausente, esa ausencia queda justificada.
        c.execute("""UPDATE reunion_asistencias a JOIN reunion_ocurrencias o ON o.id = a.ocurrencia_id
                     SET a.estado = 'justificado', a.observaciones = %s, a.updated_at = %s
                     WHERE a.empleado_id = %s AND a.fecha = %s AND a.estado = 'ausente' AND a.metodo = 'sistema'
                       AND o.id <> %s AND o.inicio < %s AND o.fin > %s""",
                  (f"Asistió a {r['nombre']} (superpuesta)"[:255], ahora, empleado["id"], fecha, occ["id"],
                   occ["fin"], occ["inicio"]))
        if previo:
            c.execute("UPDATE reunion_asistencias SET estado=%s, registrado_at=%s, metodo=%s, lat=%s, lon=%s, updated_at=%s"
                      " WHERE id=%s", (*datos.values(), previo["id"]))
        else:
            try:
                db.insert(c, "reunion_asistencias", dict(
                    empresa_id=r["empresa_id"], reunion_id=r["id"], sucursal_id=r["sucursal_id"],
                    ocurrencia_id=occ["id"], empleado_id=empleado["id"], fecha=fecha, **datos))
            except IntegrityError:  # doble escaneo simultaneo
                previo = db.one(c, "SELECT * FROM reunion_asistencias WHERE ocurrencia_id = %s AND empleado_id = %s",
                                (occ["id"], empleado["id"]))
                return _registro_dict(r, occ, previo, True)
        return _registro_dict(r, occ, dict(estado=estado, registrado_at=ahora), False)


def marcar_manual(who, reunion_id, fecha, empleado_id, estado, observaciones=None, *, sucursal_id=SIN_SEDE, ahora=None):
    """Carga o corrige la asistencia desde el panel (presente, tarde, ausente o justificado)."""
    if estado not in ESTADOS:
        raise Error("Estado inválido.")
    ahora = ahora or now_local()
    fecha = _date(fecha)
    if fecha > ahora.date():
        raise Error("No se puede cargar asistencia de una fecha futura.")
    with db.transaction() as c:
        r = sede(c, obtener(c, who, reunion_id), sucursal_id)
        if not ocurre_en(r, fecha) and not ocurrencia(c, r, fecha, crear=False):
            raise Error("La reunión no ocurre en esa fecha.")
        empleado = db.one(c, "SELECT id, empresa_id FROM empleados WHERE id = %s AND empresa_id = %s",
                          (empleado_id, r["empresa_id"]))
        if not empleado:
            raise Error("Empleado inválido.")
        occ = ocurrencia(c, r, fecha, lock=True)
        if occ["estado"] == "cancelada":
            raise Error("La reunión de esa fecha está cancelada.")
        obs = (observaciones or "").strip()[:255] or None
        previo = db.one(c, "SELECT id FROM reunion_asistencias WHERE ocurrencia_id = %s AND empleado_id = %s",
                        (occ["id"], empleado["id"]))
        registrado = ahora if estado in ("presente", "tarde") else None
        if previo:
            c.execute("UPDATE reunion_asistencias SET estado=%s, metodo='manual', usuario_id=%s, observaciones=%s,"
                      " registrado_at=COALESCE(registrado_at, %s), updated_at=%s WHERE id=%s",
                      (estado, who.get("user_id"), obs, registrado, ahora, previo["id"]))
        else:
            db.insert(c, "reunion_asistencias", dict(
                empresa_id=r["empresa_id"], reunion_id=r["id"], sucursal_id=r["sucursal_id"], ocurrencia_id=occ["id"],
                empleado_id=empleado["id"], fecha=fecha, estado=estado, registrado_at=registrado, metodo="manual",
                usuario_id=who.get("user_id"), observaciones=obs, updated_at=ahora))


def reprogramar_ocurrencia(who, reunion_id, fecha, hora=None, motivo=None, *, sucursal_id=None, restaurar=False,
                           ahora=None):
    """Cambia el horario de una sola fecha (en una sede o en todas; sucursal_id None = todas), o lo
    devuelve al habitual. Solo sin registros de asistencia y hacia un horario que todavia no paso."""
    ahora = ahora or now_local()
    fecha = _date(fecha)
    with db.transaction() as c:
        base = obtener(c, who, reunion_id)
        objetivo = sedes_efectivas(c, base) if sucursal_id is None else [sede(c, base, sucursal_id)]
        objetivo = [r for r in objetivo if ocurre_en(r, fecha) or ocurrencia(c, r, fecha, crear=False)]
        if not objetivo:
            raise Error("La reunión no ocurre en esa fecha.")
        nueva = None if restaurar else _hora(hora, "Nuevo horario")
        for r in objetivo:
            occ = ocurrencia(c, r, fecha, lock=True)
            if occ["estado"] != "programada":
                raise Error("Esa fecha ya está cerrada o cancelada: no se puede cambiar el horario.")
            if db.one(c, "SELECT 1 AS x FROM reunion_asistencias WHERE ocurrencia_id=%s LIMIT 1", (occ["id"],)):
                raise Error("Esa fecha ya tiene registros de asistencia: no se puede cambiar el horario.")
            habitual = horarios(r, fecha)
            if restaurar:
                h, marca, nota = habitual, 0, motivo_cambio(info_fecha(r, fecha))
            else:
                minutos = nueva.hour * 60 + nueva.minute
                if minutos + int(r["duracion_min"]) > 23 * 60 + 59:
                    raise Error("Con ese horario la reunión terminaría al día siguiente.")
                h = horarios(dict(r, hora_inicio=nueva.strftime("%H:%M:00")), fecha)
                if h["inicio"] <= ahora:
                    raise Error("El nuevo horario ya pasó.")
                detalle = (motivo or "").strip()
                nota = f"Horario cambiado a las {nueva.strftime('%H:%M')} (habitual {_hhmm(habitual['inicio'])})."
                if detalle:
                    nota = f"{nota[:-1]}: {detalle}"
                marca = 1
            c.execute("""UPDATE reunion_ocurrencias SET inicio=%s, fin=%s, ventana_desde=%s, ventana_hasta=%s,
                         tarde_desde=%s, reprogramada=%s, motivo_cambio=%s WHERE id=%s""",
                      (h["inicio"], h["fin"], h["ventana_desde"], h["ventana_hasta"], h["tarde_desde"], marca,
                       (nota or None) and nota[:255], occ["id"]))
    return len(objetivo)


def cancelar_ocurrencia(who, reunion_id, fecha, motivo, *, cancelar=True, sucursal_id=None):
    """Cancela (o reactiva) la fecha en una sede; sucursal_id None = en todas las sedes."""
    fecha = _date(fecha)
    with db.transaction() as c:
        base = obtener(c, who, reunion_id)
        objetivo = sedes_efectivas(c, base) if sucursal_id is None else [sede(c, base, sucursal_id)]
        if not any(ocurre_en(r, fecha) or ocurrencia(c, r, fecha, crear=False) for r in objetivo):
            raise Error("La reunión no ocurre en esa fecha.")
        motivo = (motivo or "").strip()[:255]
        if cancelar and not motivo:
            raise Error("Indicá el motivo de la cancelación.")
        for r in objetivo:
            occ = ocurrencia(c, r, fecha, lock=True)
            if cancelar:
                # Los ausentes generados por el cierre dejan de contar: la fecha no se tiene en cuenta.
                c.execute("UPDATE reunion_ocurrencias SET estado='cancelada', motivo_cancelacion=%s WHERE id=%s",
                          (motivo, occ["id"]))
            else:
                c.execute("UPDATE reunion_ocurrencias SET estado='programada', motivo_cancelacion=NULL, cerrada_at=NULL"
                          " WHERE id=%s", (occ["id"],))
                c.execute("DELETE FROM reunion_asistencias WHERE ocurrencia_id=%s AND metodo='sistema'", (occ["id"],))


# --- CRUD -------------------------------------------------------------------------------

def obtener(c, who, reunion_id, lock=False):
    r = db.one(c, "SELECT * FROM reuniones WHERE id = %s AND empresa_id = %s" + (" FOR UPDATE" if lock else ""),
               (int(reunion_id), who["empresa_id"]))
    if not r:
        raise Error("Reunión no encontrada.", 404)
    return r


def reglas(c, reunion_id):
    return db.all_rows(c, "SELECT empleado_id, sector_id, puesto_id FROM reunion_participantes WHERE reunion_id = %s",
                       (reunion_id,))


def _hora(raw, nombre):
    try:
        return _time(str(raw or ""))
    except (ValueError, TypeError):
        raise Error(f"{nombre}: hora inválida (HH:MM).")


def _validar(data):
    nombre = str(data.get("nombre") or "").strip()
    if not nombre or len(nombre) > 150:
        raise Error("Nombre: obligatorio, hasta 150 caracteres.")
    frecuencia = data.get("frecuencia")
    if frecuencia not in FRECUENCIAS:
        raise Error("Frecuencia inválida.")
    dias = sorted({int(d) for d in (data.get("dias_semana") or []) if str(d).isdigit() and 0 <= int(d) <= 6})
    out = dict(nombre=nombre, frecuencia=frecuencia, mensual_tipo=None, dia_mes=None, semana_mes=None,
               descripcion=(str(data.get("descripcion") or "").strip()[:1000] or None),
               lugar=(str(data.get("lugar") or "").strip()[:150] or None))
    if frecuencia in ("diaria", "semanal"):
        if not dias:
            raise Error("Elegí al menos un día de la semana.")
        out["dias_semana"] = ",".join(map(str, dias))
    else:
        out["mensual_tipo"] = data.get("mensual_tipo") if data.get("mensual_tipo") in ("dia", "semana") else "dia"
        if out["mensual_tipo"] == "dia":
            out["dia_mes"] = _int(data.get("dia_mes"), "Día del mes", 1, 31)
            out["dias_semana"] = None
        else:
            out["semana_mes"] = _int(data.get("semana_mes"), "Semana del mes", 1, 5)
            out["dias_semana"] = str(_int(data.get("dia_semana_mes"), "Día de la semana", 0, 6))
    hora = _hora(data.get("hora_inicio"), "Hora de inicio")
    out["hora_inicio"] = hora.strftime("%H:%M:00")
    out["duracion_min"] = _int(data.get("duracion_min"), "Duración (minutos)", 5, 720, 60)
    if hora.hour * 60 + hora.minute + out["duracion_min"] > 23 * 60 + 59:
        raise Error("La reunión debe terminar el mismo día (antes de las 23:59).")
    out["tolerancia_antes_min"] = _int(data.get("tolerancia_antes_min"), "Registro anticipado", 0, 180, 15)
    out["tarde_despues_min"] = _int(data.get("tarde_despues_min"), "Tolerancia de llegada", 0, out["duracion_min"], 10)
    cierre = str(data.get("cierre_despues_min") or "").strip()
    out["cierre_despues_min"] = None if cierre == "" else _int(cierre, "Cierre del registro", 0, out["duracion_min"])
    if out["cierre_despues_min"] is not None and out["cierre_despues_min"] < out["tarde_despues_min"]:
        raise Error("El cierre del registro no puede ser anterior a la tolerancia de llegada.")
    try:
        out["fecha_inicio"] = _date(data.get("fecha_inicio") or now_local().date())
        out["fecha_fin"] = _date(data["fecha_fin"]) if data.get("fecha_fin") else None
    except ValueError:
        raise Error("Fecha inválida.")
    if out["fecha_fin"] and out["fecha_fin"] < out["fecha_inicio"]:
        raise Error("La fecha de fin no puede ser anterior a la de inicio.")
    out["qr_modo"] = data.get("qr_modo") if data.get("qr_modo") in QR_MODOS else "fijo"
    out["feriado_accion"] = data.get("feriado_accion") if data.get("feriado_accion") in FERIADO_ACCIONES else "posponer"
    out["activa"] = 0 if str(data.get("activa", "1")) == "0" else 1
    return out


def _sedes_validas(c, empresa_id, data, duracion):
    """[{sucursal_id, lugar, hora_inicio}] del formulario; vacio = sesion unica para todos."""
    salida = []
    pedidas = data.get("sedes") or []
    if not pedidas:
        return salida
    ids = {int(s["sucursal_id"]) for s in pedidas if str(s.get("sucursal_id", "")).isdigit()}
    validas = {row["id"]: row["nombre"] for row in db.all_rows(
        c, f"SELECT id, nombre FROM sucursales WHERE empresa_id = %s AND id IN ({_marcas(ids)})", (empresa_id, *ids))}
    for s in pedidas:
        sid = int(s["sucursal_id"]) if str(s.get("sucursal_id", "")).isdigit() else None
        if sid not in validas:
            raise Error("Sucursal inválida.")
        hora = None
        if str(s.get("hora_inicio") or "").strip():
            hora = _hora(s["hora_inicio"], f"Hora en {validas[sid]}")
            if hora.hour * 60 + hora.minute + duracion > 23 * 60 + 59:
                raise Error(f"En {validas[sid]} la reunión debe terminar el mismo día.")
        salida.append(dict(sucursal_id=sid, lugar=(str(s.get("lugar") or "").strip()[:150] or None),
                           hora_inicio=hora.strftime("%H:%M:00") if hora else None))
    return salida


def _participantes(c, empresa_id, data):
    """Reglas del formulario: 'todos', '<sector>', '<sector>:<puesto>', ':<puesto>' y empleados por ID."""
    sectores = {row["id"] for row in db.all_rows(c, "SELECT id FROM sectores WHERE empresa_id=%s", (empresa_id,))}
    puestos = {row["id"] for row in db.all_rows(c, "SELECT id FROM puestos WHERE empresa_id=%s", (empresa_id,))}
    salida = set()
    for regla in data.get("reglas") or []:
        regla = str(regla).strip()
        if regla == "todos":
            salida.add((None, None, None))
            continue
        sector, _, puesto = regla.partition(":")
        s_id = int(sector) if sector.isdigit() else None
        p_id = int(puesto) if puesto.isdigit() else None
        if (sector and s_id not in sectores) or (puesto and p_id not in puestos) or (s_id is None and p_id is None):
            raise Error("Sector o puesto inválido.")
        salida.add((None, s_id, p_id))
    ids = {int(x) for x in data.get("empleados") or [] if str(x).isdigit()}
    if ids:
        validos = {row["id"] for row in db.all_rows(
            c, f"SELECT id FROM empleados WHERE empresa_id=%s AND id IN ({_marcas(ids)})", (empresa_id, *ids))}
        if validos != ids:
            raise Error("Hay empleados que no pertenecen a la empresa.")
        salida |= {(i, None, None) for i in ids}
    if not salida:
        raise Error("Asigná al menos un participante: empleados, sectores, puestos o toda la empresa.")
    if (None, None, None) in salida:  # toda la empresa ya incluye al resto
        salida = {(None, None, None)}
    return salida


def guardar(who, data, reunion_id=None):
    valores = _validar(data)
    ahora = now_local()
    with db.transaction() as c:
        reglas_nuevas = _participantes(c, who["empresa_id"], data)
        sedes_nuevas = _sedes_validas(c, who["empresa_id"], data, valores["duracion_min"])
        if reunion_id:
            obtener(c, who, reunion_id, lock=True)
            sets = ", ".join(f"{k}=%s" for k in valores)
            c.execute(f"UPDATE reuniones SET {sets}, updated_at=%s WHERE id=%s", (*valores.values(), ahora, reunion_id))
            c.execute("DELETE FROM reunion_participantes WHERE reunion_id=%s", (reunion_id,))
            c.execute("DELETE FROM reunion_sedes WHERE reunion_id=%s", (reunion_id,))
            # Las ocurrencias futuras sin registros toman el horario nuevo.
            c.execute("""DELETE o FROM reunion_ocurrencias o WHERE o.reunion_id=%s AND o.estado='programada'
                         AND o.reprogramada = 0 AND o.inicio > %s
                         AND NOT EXISTS (SELECT 1 FROM reunion_asistencias a WHERE a.ocurrencia_id=o.id)""",
                      (reunion_id, ahora))
        else:
            reunion_id = db.insert(c, "reuniones", dict(valores, empresa_id=who["empresa_id"], creado_por=who.get("user_id"),
                                                         qr_version=1, created_at=ahora, updated_at=ahora))
        for empleado_id, sector_id, puesto_id in sorted(reglas_nuevas, key=str):
            db.insert(c, "reunion_participantes", dict(reunion_id=reunion_id, empleado_id=empleado_id,
                                                        sector_id=sector_id, puesto_id=puesto_id))
        for item in sedes_nuevas:
            db.insert(c, "reunion_sedes", dict(item, reunion_id=reunion_id))
    return reunion_id


def eliminar(who, reunion_id):
    """Elimina la reunion si no tiene asistencias; con historial solo se puede desactivar."""
    with db.transaction() as c:
        obtener(c, who, reunion_id, lock=True)
        if db.one(c, "SELECT 1 AS x FROM reunion_asistencias WHERE reunion_id=%s LIMIT 1", (reunion_id,)):
            raise Error("La reunión tiene asistencias registradas: desactivala para conservar las estadísticas.", 409)
        c.execute("DELETE FROM reuniones WHERE id=%s", (reunion_id,))


def regenerar_qr(who, reunion_id):
    """Nueva version de los QR impresos (de todas las sedes): los anteriores dejan de funcionar."""
    with db.transaction() as c:
        obtener(c, who, reunion_id, lock=True)
        c.execute("UPDATE reuniones SET qr_version = qr_version + 1, updated_at=%s WHERE id=%s", (now_local(), reunion_id))


def sucursales(who):
    with db.transaction(read_only=True) as c:
        return db.all_rows(c, "SELECT id, nombre FROM sucursales WHERE empresa_id=%s ORDER BY nombre", (who["empresa_id"],))


# --- Superposiciones ---------------------------------------------------------------------------

DIAS_SUPERPOSICION = 60


def superposiciones(c, empresa_id, desde, hasta, reunion_id=None):
    """Pares de reuniones (cada una en su sede) que el mismo dia se pisan en horario y comparten
    convocados. Con reunion_id, solo los pares en los que participa esa reunion."""
    feriados = feriado_service.mapa(c, empresa_id)
    canceladas = {(o["reunion_id"], o["sucursal_id"], o["fecha"]) for o in db.all_rows(
        c, "SELECT reunion_id, sucursal_id, fecha FROM reunion_ocurrencias WHERE empresa_id=%s AND estado='cancelada'"
           " AND fecha BETWEEN %s AND %s", (empresa_id, desde, hasta))}
    guardadas = _guardadas(c, desde, hasta, empresa_id)
    por_fecha = {}
    for r in db.all_rows(c, "SELECT * FROM reuniones WHERE empresa_id=%s AND activa=1", (empresa_id,)):
        for x in sedes_efectivas(c, r, None, feriados):
            for f in fechas(x, desde, hasta):
                if (x["id"], x["sucursal_id"], f) not in canceladas:
                    h = guardadas.get((x["id"], x["sucursal_id"], f)) or horarios(x, f)
                    por_fecha.setdefault(f, []).append((x, h))
    cache = {}

    def gente(x):
        clave = (x["id"], x["sucursal_id"])
        if clave not in cache:
            cache[clave] = {e["id"] for e in convocados(c, x, x["sucursal_id"] or None)}
        return cache[clave]

    salida = []
    for fecha, lista in sorted(por_fecha.items()):
        for i, (a, ha) in enumerate(lista):
            for b, hb in lista[i + 1:]:
                if a["id"] == b["id"] or (reunion_id and reunion_id not in (a["id"], b["id"])):
                    continue
                if not (ha["inicio"] < hb["fin"] and hb["inicio"] < ha["fin"]):
                    continue
                comunes = gente(a) & gente(b)
                if comunes:
                    salida.append(dict(fecha=fecha, empleados=len(comunes), reuniones=[
                        dict(id=x["id"], nombre=x["nombre"], sucursal_nombre=x.get("sucursal_nombre"),
                             inicio=_hhmm(h["inicio"]), fin=_hhmm(h["fin"])) for x, h in ((a, ha), (b, hb))]))
    return salida


def conflictos(who, reunion_id, dias=DIAS_SUPERPOSICION, *, desde=None):
    """Superposiciones de una reunion en los proximos dias, agrupadas por la otra reunion."""
    desde = desde or now_local().date()
    with db.transaction(read_only=True) as c:
        pares = superposiciones(c, who["empresa_id"], desde, desde + dt.timedelta(days=dias), int(reunion_id))
    grupos = {}
    for par in pares:
        propia, otra = sorted(par["reuniones"], key=lambda x: x["id"] != int(reunion_id))
        g = grupos.setdefault(otra["id"], dict(reunion_id=otra["id"], nombre=otra["nombre"], fechas=0, empleados=0,
                                               primera=par["fecha"], horario=f"{otra['inicio']} a {otra['fin']}",
                                               sucursal_nombre=otra.get("sucursal_nombre")))
        g["fechas"] += 1
        g["empleados"] = max(g["empleados"], par["empleados"])
    return sorted(grupos.values(), key=lambda g: (g["primera"], g["nombre"]))


def reuniones_con_superposicion(who, dias=DIAS_SUPERPOSICION):
    """{reunion_id: cantidad de fechas superpuestas} para marcar las tarjetas del listado."""
    hoy = now_local().date()
    with db.transaction(read_only=True) as c:
        pares = superposiciones(c, who["empresa_id"], hoy, hoy + dt.timedelta(days=dias))
    conteo = {}
    for par in pares:
        for x in par["reuniones"]:
            conteo[x["id"]] = conteo.get(x["id"], 0) + 1
    return conteo


# --- Consultas del panel -------------------------------------------------------------------

_CONTEOS = ("convocatorias", "presentes", "tarde", "ausentes", "justificados")


def _agregado(where, args):
    return f"""SELECT COUNT(*) AS convocatorias,
                      COALESCE(SUM(a.estado='presente'),0) AS presentes,
                      COALESCE(SUM(a.estado='tarde'),0) AS tarde,
                      COALESCE(SUM(a.estado='ausente'),0) AS ausentes,
                      COALESCE(SUM(a.estado='justificado'),0) AS justificados,
                      COALESCE(SUM(CASE WHEN a.estado IN ('presente','tarde')
                                        THEN TIMESTAMPDIFF(MINUTE, o.inicio, o.fin) ELSE 0 END),0) AS minutos_asistidos
               FROM reunion_asistencias a JOIN reunion_ocurrencias o ON o.id = a.ocurrencia_id
               WHERE o.estado <> 'cancelada' AND {where}""", args


def _agrupado(c, where, args, campos, joins=""):
    """Agregado agrupado por campos ('a.reunion_id, r.nombre AS nombre') con joins extra."""
    grupo = ", ".join(campo.split(" AS ")[0] for campo in campos.split(", "))
    sql, params = _agregado(f"{where} GROUP BY {grupo}", args)
    sql = sql.replace("SELECT COUNT(*)", f"SELECT {campos}, COUNT(*)")
    if joins:
        sql = sql.replace("JOIN reunion_ocurrencias o", f"{joins} JOIN reunion_ocurrencias o")
    return [_tasas(row) for row in db.all_rows(c, sql, params)]


def _tasas(row):
    row = {k: int(v or 0) if k in _CONTEOS else v for k, v in row.items()}
    asistidas = row["presentes"] + row["tarde"]
    row["asistidas"] = asistidas
    row["asistencia_pct"] = pct(asistidas, row["convocatorias"] - row["justificados"])
    row["puntualidad_pct"] = pct(row["presentes"], asistidas)
    if "minutos_asistidos" in row:
        row["minutos_asistidos"] = int(row["minutos_asistidos"] or 0)
        row["horas_asistidas"] = round(row["minutos_asistidos"] / 60, 1)
    return row


def _suma(filas):
    claves = _CONTEOS + (("minutos_asistidos",) if filas and all("minutos_asistidos" in x for x in filas) else ())
    return _tasas({k: sum(x[k] for x in filas) for k in claves})


def _filtro_sucursal(sucursal_id, alias="a"):
    if sucursal_id is None or sucursal_id == "":
        return "", ()
    return f" AND {alias}.sucursal_id = %s", (int(sucursal_id),)


def listado(who, *, q=None, estado=None, sucursal_id=None, desde=None, hasta=None):
    ahora = now_local()
    hasta = hasta or ahora.date()
    desde = desde or hasta - dt.timedelta(days=29)
    where, args = ["r.empresa_id=%s"], [who["empresa_id"]]
    if q:
        where.append("(r.nombre LIKE %s OR r.lugar LIKE %s)")
        args += [f"%{q}%"] * 2
    if estado in ("activas", "inactivas"):
        where.append("r.activa=%s")
        args.append(1 if estado == "activas" else 0)
    if sucursal_id:
        where.append("(NOT EXISTS (SELECT 1 FROM reunion_sedes rs WHERE rs.reunion_id=r.id)"
                     " OR EXISTS (SELECT 1 FROM reunion_sedes rs WHERE rs.reunion_id=r.id AND rs.sucursal_id=%s))")
        args.append(int(sucursal_id))
    filtro, extra = _filtro_sucursal(sucursal_id)
    with db.transaction(read_only=True) as c:
        rows = db.all_rows(c, f"SELECT r.* FROM reuniones r WHERE {' AND '.join(where)} ORDER BY r.activa DESC, r.nombre",
                           tuple(args))
        cantidades = contar_convocados(c, who["empresa_id"])
        stats = {row["reunion_id"]: row for row in _agrupado(
            c, "a.empresa_id=%s AND a.fecha BETWEEN %s AND %s" + filtro, (who["empresa_id"], desde, hasta, *extra),
            "a.reunion_id")}
        hoy = db.all_rows(c, "SELECT reunion_id, sucursal_id, estado FROM reunion_ocurrencias WHERE empresa_id=%s AND fecha=%s",
                          (who["empresa_id"], ahora.date()))
        por_reunion = {r["id"]: sedes(c, r["id"]) for r in rows}
        feriados = feriado_service.mapa(c, who["empresa_id"])
        efectivas = {r["id"]: sedes_efectivas(c, r, por_reunion[r["id"]], feriados) for r in rows}
    canceladas_hoy = {(row["reunion_id"], row["sucursal_id"]) for row in hoy if row["estado"] == "cancelada"}
    for r in rows:
        r["sedes"] = por_reunion[r["id"]]
        r["descripcion_frecuencia"] = describir(r)
        r["convocados"] = cantidades.get(r["id"], 0)
        proximas_sedes = [f for f in (proxima_fecha(x, ahora.date()) for x in efectivas[r["id"]]) if f]
        r["proxima"] = min(proximas_sedes) if r["activa"] and proximas_sedes else None
        r["stats"] = stats.get(r["id"])
        r["hoy"] = bool(r["activa"] and any(ocurre_en(x, ahora.date()) and (r["id"], x["sucursal_id"]) not in canceladas_hoy
                                            for x in efectivas[r["id"]]))
    return dict(reuniones=rows, total=_suma(list(stats.values())), desde=desde, hasta=hasta)


def detalle(who, reunion_id, *, desde=None, hasta=None, sucursal_id=None):
    ahora = now_local()
    hasta = hasta or ahora.date()
    desde = desde or hasta - dt.timedelta(days=89)
    filtro_o, extra = _filtro_sucursal(sucursal_id, "o")
    filtro_a, _ = _filtro_sucursal(sucursal_id, "a")
    with db.transaction(read_only=True) as c:
        r = obtener(c, who, reunion_id)
        r["sedes"] = sedes(c, r["id"])
        efectivas = sedes_efectivas(c, r, r["sedes"])
        lista = convocados(c, r, sucursal_id or None)
        r["reglas"] = reglas(c, r["id"])
        ocurrencias = db.all_rows(c, f"""
            SELECT o.*, su.nombre AS sucursal_nombre, COUNT(a.id) AS convocatorias,
                   COALESCE(SUM(a.estado='presente'),0) AS presentes, COALESCE(SUM(a.estado='tarde'),0) AS tarde,
                   COALESCE(SUM(a.estado='ausente'),0) AS ausentes, COALESCE(SUM(a.estado='justificado'),0) AS justificados
            FROM reunion_ocurrencias o LEFT JOIN reunion_asistencias a ON a.ocurrencia_id = o.id
            LEFT JOIN sucursales su ON su.id = o.sucursal_id
            WHERE o.reunion_id=%s AND o.fecha BETWEEN %s AND %s{filtro_o}
            GROUP BY o.id ORDER BY o.fecha DESC, su.nombre""", (r["id"], desde, hasta, *extra))
        args = (r["id"], desde, hasta, *extra)
        ranking = _agrupado(c, "a.reunion_id=%s AND a.fecha BETWEEN %s AND %s" + filtro_a, args,
                            "a.empleado_id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre,"
                            " su.nombre AS sucursal_nombre",
                            "JOIN empleados e ON e.id = a.empleado_id LEFT JOIN sectores s ON s.id = e.sector_id"
                            " LEFT JOIN sucursales su ON su.id = a.sucursal_id")
        por_sede = _agrupado(c, "a.reunion_id=%s AND a.fecha BETWEEN %s AND %s" + filtro_a, args,
                             "a.sucursal_id, su.nombre AS sucursal_nombre",
                             "LEFT JOIN sucursales su ON su.id = a.sucursal_id")
    for o in ocurrencias:
        o.update(_tasas({k: o[k] for k in _CONTEOS}))
    ranking.sort(key=lambda x: (x["asistencia_pct"] is None, x["asistencia_pct"] or 0, x["apellido"] or ""))
    r["descripcion_frecuencia"] = describir(r)
    if sucursal_id not in (None, ""):
        efectivas = [x for x in efectivas if x["sucursal_id"] == int(sucursal_id)]
    proximas = []
    if r["activa"]:
        with db.transaction(read_only=True) as c:
            guardadas = _guardadas(c, ahora.date(), ahora.date() + dt.timedelta(days=60), r["empresa_id"])
        for item in efectivas:
            for x in calendario(item, ahora.date(), ahora.date() + dt.timedelta(days=60))[:6]:
                occ = guardadas.get((item["id"], item["sucursal_id"], x["fecha"]))
                proximas.append(dict(fecha=x["fecha"], sucursal_id=item["sucursal_id"], sucursal_nombre=item["sucursal_nombre"],
                                     hora=_hhmm(occ["inicio"]) if occ else _hhmm(_time(item["hora_inicio"])),
                                     original=x["original"], omitida=x["omitida"],
                                     reprogramada=bool(occ and occ.get("reprogramada")),
                                     motivo=(occ or {}).get("motivo_cambio") or motivo_cambio(x)))
        proximas.sort(key=lambda x: (x["fecha"], x["sucursal_nombre"] or ""))
    return dict(reunion=r, sedes_efectivas=efectivas, convocados=lista, ocurrencias=ocurrencias, ranking=ranking,
                por_sede=por_sede, total=_suma(por_sede), proximas=proximas[:12], desde=desde, hasta=hasta,
                sucursal_id=sucursal_id)


def ocurrencia_detalle(who, reunion_id, fecha, sucursal_id=SIN_SEDE):
    fecha = _date(fecha)
    ahora = now_local()
    with db.transaction(read_only=True) as c:
        base = obtener(c, who, reunion_id)
        r = sede(c, base, sucursal_id)
        occ = ocurrencia(c, r, fecha, crear=False)
        if not occ and not ocurre_en(r, fecha):
            movida = info_fecha(r, fecha)
            if movida and movida["feriado"]:
                raise Error(motivo_cambio(movida) or f"Feriado: {movida['feriado']}.", 404)
            raise Error("La reunión no ocurre en esa fecha.", 404)
        registros = {row["empleado_id"]: row for row in db.all_rows(
            c, "SELECT * FROM reunion_asistencias WHERE ocurrencia_id=%s", (occ["id"],))} if occ else {}
        lista = convocados(c, r, r["sucursal_id"])
        extra = set(registros) - {e["id"] for e in lista}
        if extra:  # registrados que ya no estan convocados (o inactivos): se muestran igual
            lista += db.all_rows(c, f"SELECT e.id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre FROM empleados e"
                                    f" LEFT JOIN sectores s ON s.id=e.sector_id WHERE e.id IN ({_marcas(extra)})",
                                 tuple(extra))
        otras = [x for x in sedes_efectivas(c, base) if x["sucursal_id"] != r["sucursal_id"] and ocurre_en(x, fecha)]
    h = occ or horarios(r, fecha)
    filas = []
    for e in lista:
        reg = registros.get(e["id"])
        filas.append(dict(e, estado=reg["estado"] if reg else "pendiente", registrado_at=reg["registrado_at"] if reg else None,
                          metodo=reg["metodo"] if reg else None, observaciones=reg["observaciones"] if reg else None))
    conteo = {k: sum(1 for f in filas if f["estado"] == k) for k in ESTADOS + ("pendiente",)}
    cambio = (occ or {}).get("motivo_cambio") or motivo_cambio(info_fecha(r, fecha))
    return dict(reunion=r, fecha=fecha, ocurrencia=occ, horario=h, filas=filas, conteo=conteo, otras_sedes=otras, cambio=cambio,
                ahora=ahora,
                abierta=h["ventana_desde"] <= ahora <= h["ventana_hasta"], futura=fecha > ahora.date())


def estadisticas_empresa(who, desde, hasta, sucursal_id=None):
    """Resumen por reunion, por sucursal y por empleado (los de menor asistencia primero)."""
    filtro, extra = _filtro_sucursal(sucursal_id)
    base = "a.empresa_id=%s AND a.fecha BETWEEN %s AND %s" + filtro
    args = (who["empresa_id"], desde, hasta, *extra)
    with db.transaction(read_only=True) as c:
        por_reunion = _agrupado(c, base, args, "a.reunion_id, r.nombre AS nombre", "JOIN reuniones r ON r.id = a.reunion_id")
        por_sucursal = _agrupado(c, base, args, "a.sucursal_id, su.nombre AS sucursal_nombre",
                                 "LEFT JOIN sucursales su ON su.id = a.sucursal_id")
        por_empleado = _agrupado(c, base, args, "a.empleado_id, e.apellido, e.nombre, e.legajo, su.nombre AS sucursal_nombre",
                                 "JOIN empleados e ON e.id = a.empleado_id LEFT JOIN sucursales su ON su.id = e.sucursal_id")
        serie = db.all_rows(c, f"""SELECT a.fecha, COUNT(*) AS convocatorias,
                COALESCE(SUM(a.estado IN ('presente','tarde')),0) AS asistidas, COALESCE(SUM(a.estado='justificado'),0) AS justificados
            FROM reunion_asistencias a JOIN reunion_ocurrencias o ON o.id=a.ocurrencia_id
            WHERE o.estado<>'cancelada' AND {base} GROUP BY a.fecha ORDER BY a.fecha""", args)
    por_reunion.sort(key=lambda x: (x["asistencia_pct"] is None, x["asistencia_pct"] or 0))
    por_sucursal.sort(key=lambda x: (x["sucursal_nombre"] is None, x["sucursal_nombre"] or ""))
    por_empleado.sort(key=lambda x: (x["asistencia_pct"] is None, x["asistencia_pct"] or 0, x["apellido"] or ""))
    for row in serie:
        row["asistencia_pct"] = pct(int(row["asistidas"]), int(row["convocatorias"]) - int(row["justificados"]))
    return dict(por_reunion=por_reunion, por_sucursal=por_sucursal, por_empleado=por_empleado, serie=serie,
                total=_suma(por_reunion))


# --- API del empleado ------------------------------------------------------------------------

def reunion_publica(r):
    """r = reunion en la sede del empleado (en_sede)."""
    return dict(
        id=r["id"], nombre=r["nombre"], descripcion=r.get("descripcion"), lugar=r.get("lugar"),
        sucursal_id=r.get("sucursal_id") or None, sucursal_nombre=r.get("sucursal_nombre"),
        frecuencia=r["frecuencia"], dias_semana=_dias(r.get("dias_semana")), mensual_tipo=r.get("mensual_tipo"),
        dia_mes=r.get("dia_mes"), semana_mes=r.get("semana_mes"), hora_inicio=_hhmm(_time(r["hora_inicio"])),
        duracion_min=int(r["duracion_min"]), descripcion_frecuencia=describir(r), qr_modo=r["qr_modo"],
        tolerancia_antes_min=int(r["tolerancia_antes_min"]), tarde_despues_min=int(r["tarde_despues_min"]),
        cierre_despues_min=r.get("cierre_despues_min"), fecha_inicio=_iso(_date(r["fecha_inicio"])),
        fecha_fin=_iso(_date(r["fecha_fin"])) if r.get("fecha_fin") else None,
        feriado_accion=r.get("feriado_accion") or "posponer",
    )


def mis_reuniones(empleado, *, ahora=None):
    ahora = ahora or now_local()
    with db.transaction(read_only=True) as c:
        rows = _de_empleado_en_sede(c, empleado)
        stats = {row["reunion_id"]: row for row in _agrupado(c, "a.empleado_id=%s", (empleado["id"],), "a.reunion_id")}
    items = []
    for r in rows:
        item = reunion_publica(r)
        item["proxima_fecha"] = _iso(proxima_fecha(r, ahora.date()))
        item["mis_estadisticas"] = stats.get(r["id"]) or _tasas(dict(dict.fromkeys(_CONTEOS, 0), minutos_asistidos=0))
        item["mis_estadisticas"].pop("reunion_id", None)
        items.append(item)
    return items


# --- Ocurrencias del empleado: una sola regla para proximas, calendario, detalle y estadisticas ------------

ZONA_HORARIA = "America/Argentina/Buenos_Aires"
PROXIMAS_MAX_DIAS = 62
PROXIMAS_MAX_SEMANAS = 8
EVOLUCION_MAX_MESES = 12
ESTADOS_REALIZADA = ("presente", "tarde", "ausente", "justificado")
ESTADOS_PROXIMA = ("pendiente", "abierta")

DEFINICIONES = {
    "planificadas": "Reuniones del período no canceladas (realizadas + próximas).",
    "realizadas": "Reuniones no canceladas cuya ventana de registro ya cerró o en las que el empleado ya registró "
                  "(presente, tarde, ausente o justificado; incluye ausencias provisorias).",
    "proximas": "Reuniones no canceladas que todavía no empezaron o tienen el registro abierto (pendiente o abierta).",
    "asistidas": "presentes + tarde.",
    "ausentes": "Ausencias definitivas: la reunión ya cerró y no registró. No incluye las provisorias.",
    "ausentes_provisionales": "La ventana cerró pero el servidor todavía no cerró la reunión (cada 10 min): "
                              "puede pasar a justificado. No cuentan en asistencia_pct.",
    "justificados": "Ausencias justificadas (vacaciones, franco, reunión superpuesta o RR. HH.).",
    "canceladas": "Canceladas desde el panel o que no se hacen por día no laborable. No suman horas ni convocatorias.",
    "convocatorias": "Convocatorias exigibles ya definidas: asistidas + ausentes + justificados (misma base que "
                     "/estadisticas por fechas).",
    "asistencia_pct": "asistidas / (convocatorias − justificados) × 100 = asistidas / (asistidas + ausentes) × 100. "
                      "Las justificadas, las futuras y las ausencias provisorias no entran en el denominador. "
                      "null sin denominador.",
    "puntualidad_pct": "presentes / asistidas × 100. null sin asistidas.",
    "minutos_planificados": "Duración programada de las reuniones planificadas.",
    "minutos_realizados": "Duración programada de las reuniones realizadas.",
    "minutos_asistidos": "Duración programada completa de las reuniones con presente o tarde (no se descuenta la "
                         "llegada tarde ni se mide la permanencia). Es el mismo valor que horas_asistidas.",
    "horas_*": "minutos_* / 60 con un decimal, solo para mostrar. Calcular siempre con los minutos.",
    "definitivo": "true si el estado ya no cambia solo (registrado, cerrado por el servidor, justificado o "
                  "cancelado); false para pendiente, abierta y ausencia provisoria.",
}


def _clave_ocurrencia(reunion_id, sucursal_id, fecha):
    """Id estable de la ocurrencia para la app (existe aunque la fila todavia no se haya creado)."""
    return f"{int(reunion_id)}-{int(sucursal_id or 0)}-{_date(fecha).isoformat()}"


def _registros_empleado(c, empleado, desde, hasta):
    """Asistencias del empleado en el rango con su ocurrencia y reunion (una sola consulta)."""
    return db.all_rows(
        c, """SELECT a.id AS asistencia_id, a.reunion_id, a.sucursal_id, a.fecha, a.estado, a.registrado_at,
                     a.metodo, a.observaciones, o.id AS ocurrencia_id, o.estado AS estado_ocurrencia, o.inicio, o.fin,
                     o.ventana_desde, o.ventana_hasta, o.tarde_desde, o.fecha_original, o.motivo_cambio,
                     o.motivo_cancelacion, o.reprogramada, r.nombre, r.descripcion, r.qr_modo,
                     COALESCE(rs.lugar, r.lugar) AS lugar, su.nombre AS sucursal_nombre
              FROM reunion_asistencias a
              JOIN reunion_ocurrencias o ON o.id = a.ocurrencia_id
              JOIN reuniones r ON r.id = a.reunion_id
              LEFT JOIN reunion_sedes rs ON rs.reunion_id = a.reunion_id AND rs.sucursal_id = a.sucursal_id
              LEFT JOIN sucursales su ON su.id = a.sucursal_id
              WHERE a.empleado_id = %s AND a.empresa_id = %s AND a.fecha BETWEEN %s AND %s""",
        (empleado["id"], empleado["empresa_id"], desde, hasta))


def _item_ocurrencia(base, fecha, h, occ, reg, ahora, *, omitida=False, original=None, cambio=None):
    """Una ocurrencia con el estado del empleado. base: la reunion en su sede (o la fila del registro)."""
    cancelada = bool(omitida or (occ and occ.get("estado") == "cancelada"))
    if cancelada:
        estado, definitivo = "cancelada", True
    elif reg:
        estado, definitivo = reg["estado"], True
    elif ahora > h["ventana_hasta"]:
        estado, definitivo = "ausente", False  # provisoria hasta que el servidor cierre la reunion
    elif ahora >= h["ventana_desde"]:
        estado, definitivo = "abierta", False
    else:
        estado, definitivo = "pendiente", False
    motivo_cancelacion = None
    if cancelada:
        motivo_cancelacion = (occ.get("motivo_cancelacion") if occ else None) or (cambio if omitida else None)
    return dict(
        id=_clave_ocurrencia(base["reunion_id"], base["sucursal_id"], fecha),
        ocurrencia_id=int(occ["id"]) if occ and occ.get("id") else None,
        reunion_id=int(base["reunion_id"]), nombre=base["nombre"], lugar=base.get("lugar"),
        descripcion=base.get("descripcion"), sucursal_id=int(base["sucursal_id"] or 0) or None,
        sucursal_nombre=base.get("sucursal_nombre"), fecha=fecha.isoformat(), inicio=_iso(h["inicio"]),
        fin=_iso(h["fin"]), duracion_min=int((h["fin"] - h["inicio"]).total_seconds() // 60),
        ventana_desde=_iso(h["ventana_desde"]), ventana_hasta=_iso(h["ventana_hasta"]),
        tarde_desde=_iso(h["tarde_desde"]), estado=estado, definitivo=definitivo, cancelada=cancelada,
        motivo_cancelacion=motivo_cancelacion, fecha_original=_iso(original), motivo_cambio=cambio,
        reprogramada=bool(occ and occ.get("reprogramada")),
        registrado_at=_iso(reg["registrado_at"]) if reg and reg.get("registrado_at") else None,
        observaciones=reg.get("observaciones") if reg else None, qr_modo=base.get("qr_modo"),
        puede_registrar=estado == "abierta" and ahora <= h["ventana_hasta"],
    )


def _marcar_superpuestas(items):
    por_fecha = {}
    for item in items:
        por_fecha.setdefault(item["fecha"], []).append(item)
    for item in items:
        item["superpuesta_con"] = [
            dict(reunion_id=o["reunion_id"], nombre=o["nombre"], inicio=o["inicio"], fin=o["fin"])
            for o in por_fecha[item["fecha"]] if o is not item and o["estado"] != "cancelada"
            and item["estado"] != "cancelada" and o["inicio"] < item["fin"] and item["inicio"] < o["fin"]]


def ocurrencias_empleado(c, empleado, desde, hasta, ahora):
    """Ocurrencias del empleado entre desde y hasta (como mucho MAX_RANGO_DIAS), en orden cronologico.

    - De las reglas: reuniones activas a las que esta convocado, en su sede, con recurrencia, dias no laborables,
      cancelaciones y cambios de horario guardados (reunion_ocurrencias manda sobre la regla).
    - Sus asistencias guardadas mandan sobre todo (definitivas). Las de reuniones que ya no le tocan (desactivadas,
      otra sede, convocatoria cambiada) se agregan igual: son su historia.
    - Igual que el cierre automatico: no cuentan fechas anteriores a la creacion de la reunion, y una fecha ya cerrada
      sin registro suyo no era una convocatoria suya.
    - Una fecha pospuesta por dia no laborable aparece una sola vez, en su fecha efectiva (con fecha_original)."""
    if (hasta - desde).days > MAX_RANGO_DIAS:
        raise Error("El rango máximo es de 366 días.")
    reuniones = _de_empleado_en_sede(c, empleado)
    ids = [r["id"] for r in reuniones]
    guardadas = {(o["reunion_id"], o["sucursal_id"], _date(o["fecha"])): o for o in db.all_rows(
        c, f"SELECT * FROM reunion_ocurrencias WHERE reunion_id IN ({_marcas(ids)}) AND fecha BETWEEN %s AND %s",
        (*ids, desde, hasta))} if ids else {}
    registros = {(r["reunion_id"], r["sucursal_id"], _date(r["fecha"])): r
                 for r in _registros_empleado(c, empleado, desde, hasta)}
    items, usadas = [], set()
    for r in reuniones:
        base = dict(r, reunion_id=r["id"])
        creada = r.get("created_at")
        for dia in calendario(r, desde, hasta):
            fecha = dia["fecha"]
            clave = (r["id"], r["sucursal_id"], fecha)
            occ = guardadas.get(clave)
            if clave in usadas or (dia["omitida"] and occ):
                continue  # sin duplicados; si el panel la registro igual, manda la ocurrencia guardada
            reg = registros.get(clave)
            h = occ or horarios(r, fecha)
            if not reg and not occ and creada and h["inicio"] < creada:
                continue
            if not reg and occ and occ["estado"] == "cerrada":
                continue
            usadas.add(clave)
            items.append(_item_ocurrencia(
                base, fecha, h, occ, reg, ahora, omitida=dia["omitida"],
                original=(occ or {}).get("fecha_original") or dia["original"],
                cambio=(occ or {}).get("motivo_cambio") or motivo_cambio(dia)))
    for clave, reg in registros.items():
        if clave in usadas:
            continue
        occ = dict(id=reg["ocurrencia_id"], estado=reg["estado_ocurrencia"], reprogramada=reg["reprogramada"],
                   motivo_cancelacion=reg["motivo_cancelacion"])
        items.append(_item_ocurrencia(reg, clave[2], reg, occ, reg, ahora, original=reg["fecha_original"],
                                      cambio=reg["motivo_cambio"]))
    items.sort(key=lambda x: (x["inicio"], x["nombre"], x["reunion_id"]))
    _marcar_superpuestas(items)
    return items


def _horas(minutos):
    return round(minutos / 60, 1)


def metricas(items):
    """Totales de un conjunto de ocurrencias (ver DEFINICIONES). Base en minutos; horas solo para mostrar."""
    vigentes = [i for i in items if not i["cancelada"]]
    realizadas = [i for i in vigentes if i["estado"] in ESTADOS_REALIZADA]
    cuenta = {e: sum(1 for i in vigentes if i["estado"] == e) for e in ESTADOS_REALIZADA + ESTADOS_PROXIMA}
    ausentes = sum(1 for i in vigentes if i["estado"] == "ausente" and i["definitivo"])
    asistidas = cuenta["presente"] + cuenta["tarde"]
    convocatorias = asistidas + ausentes + cuenta["justificado"]
    minutos = dict(
        planificados=sum(i["duracion_min"] for i in vigentes),
        realizados=sum(i["duracion_min"] for i in realizadas),
        asistidos=sum(i["duracion_min"] for i in vigentes if i["estado"] in ("presente", "tarde")),
    )
    return dict(
        planificadas=len(vigentes), realizadas=len(realizadas), proximas=cuenta["pendiente"] + cuenta["abierta"],
        convocatorias=convocatorias, asistidas=asistidas, presentes=cuenta["presente"], tarde=cuenta["tarde"],
        ausentes=ausentes, ausentes_provisionales=cuenta["ausente"] - ausentes, justificados=cuenta["justificado"],
        canceladas=len(items) - len(vigentes),
        provisionales=sum(1 for i in vigentes if not i["definitivo"]),
        asistencia_pct=pct(asistidas, convocatorias - cuenta["justificado"]),
        puntualidad_pct=pct(cuenta["presente"], asistidas),
        minutos_planificados=minutos["planificados"], horas_planificadas=_horas(minutos["planificados"]),
        minutos_realizados=minutos["realizados"], horas_realizadas=_horas(minutos["realizados"]),
        minutos_asistidos=minutos["asistidos"], horas_asistidas=_horas(minutos["asistidos"]),
    )


def _por_reunion(items):
    grupos = {}
    for item in items:
        grupos.setdefault(item["reunion_id"], []).append(item)
    salida = [dict(reunion_id=rid, nombre=lista[0]["nombre"], **metricas(lista)) for rid, lista in grupos.items()]
    return sorted(salida, key=lambda x: (x["nombre"], x["reunion_id"]))


def _meta(ahora, **periodo):
    return dict(periodo=periodo, zona_horaria=ZONA_HORARIA, calculado_at=_iso(ahora.replace(microsecond=0)))


def mes_param(valor, nombre="mes"):
    """'AAAA-MM' -> (primer dia, ultimo dia)."""
    texto = str(valor or "").strip()
    if len(texto) != 7 or texto[4] != "-" or not (texto[:4].isdigit() and texto[5:].isdigit()):
        raise Error(f"'{nombre}' inválido (use AAAA-MM).")
    anio, mes = int(texto[:4]), int(texto[5:])
    if not 2000 <= anio <= 2100 or not 1 <= mes <= 12:
        raise Error(f"'{nombre}' inválido (use AAAA-MM).")
    return dt.date(anio, mes, 1), dt.date(anio, mes, calendar.monthrange(anio, mes)[1])


def _siguiente_proxima(c, empleado, desde, ahora):
    """La primera reunion no cancelada que todavia no paso (para distinguir 'no hay esta semana' de 'no hay')."""
    items = ocurrencias_empleado(c, empleado, desde, desde + dt.timedelta(days=MAX_RANGO_DIAS), ahora)
    item = next((i for i in items if i["estado"] in ESTADOS_PROXIMA), None)
    return dict(reunion_id=item["reunion_id"], nombre=item["nombre"], fecha=item["fecha"], inicio=item["inicio"],
                lugar=item["lugar"], sucursal_nombre=item["sucursal_nombre"]) if item else None


def proximas(empleado, dias=7, *, desde=None, ahora=None):
    """Ocurrencias desde hoy (o desde la fecha dada, p. ej. el lunes de la semana) con el estado del
    empleado y un resumen: cantidad, horas, registradas, pendientes, ausentes y canceladas.
    proxima: la siguiente reunion por venir aunque este fuera del rango (null = no hay proximas reuniones)."""
    ahora = ahora or now_local()
    dias = max(1, min(int(dias or 7), PROXIMAS_MAX_DIAS))
    desde = desde or ahora.date()
    hasta = desde + dt.timedelta(days=dias - 1)
    with db.transaction(read_only=True) as c:
        items = ocurrencias_empleado(c, empleado, desde, hasta, ahora)
        proxima = next((i for i in items if i["estado"] in ESTADOS_PROXIMA), None)
        if proxima:
            proxima = dict(reunion_id=proxima["reunion_id"], nombre=proxima["nombre"], fecha=proxima["fecha"],
                           inicio=proxima["inicio"], lugar=proxima["lugar"], sucursal_nombre=proxima["sucursal_nombre"])
        else:
            proxima = _siguiente_proxima(c, empleado, max(hasta + dt.timedelta(days=1), ahora.date()), ahora)
    activas = [i for i in items if not i["cancelada"]]
    cuenta = {e: sum(1 for i in items if i["estado"] == e) for e in
              ("presente", "tarde", "ausente", "justificado", "abierta", "pendiente", "cancelada")}
    minutos = sum(i["duracion_min"] for i in activas)
    resumen = dict(
        reuniones=len(activas), minutos=minutos, horas=_horas(minutos),
        registradas=cuenta["presente"] + cuenta["tarde"], tarde=cuenta["tarde"],
        pendientes=cuenta["pendiente"] + cuenta["abierta"], ausentes=cuenta["ausente"],
        justificadas=cuenta["justificado"], canceladas=cuenta["cancelada"],
        superpuestas=sum(1 for i in items if i["superpuesta_con"]),
    )
    return dict(desde=desde.isoformat(), hasta=hasta.isoformat(), resumen=resumen, items=items,
                proxima=proxima, hay_proximas=proxima is not None,
                **_meta(ahora, desde=desde.isoformat(), hasta=hasta.isoformat(), dias=dias))


def calendario_mes(empleado, mes, *, ahora=None):
    """Todas las ocurrencias del mes (sin paginar ni truncar) y su resumen, con las mismas reglas del dashboard."""
    ahora = ahora or now_local()
    desde, hasta = mes_param(mes)
    with db.transaction(read_only=True) as c:
        items = ocurrencias_empleado(c, empleado, desde, hasta, ahora)
    return dict(**_meta(ahora, mes=desde.strftime("%Y-%m"), desde=desde.isoformat(), hasta=hasta.isoformat()),
                resumen=metricas(items), total=len(items), items=items)


def _estado_periodo(desde, hasta, ahora):
    if hasta < ahora.date():
        return "pasado"
    return "futuro" if desde > ahora.date() else "en_curso"


def estadisticas_mes(empleado, mes, *, ahora=None):
    """Dashboard personal del mes: totales, datos para los graficos y desglose por reunion."""
    ahora = ahora or now_local()
    desde, hasta = mes_param(mes)
    with db.transaction(read_only=True) as c:
        items = ocurrencias_empleado(c, empleado, desde, hasta, ahora)
    totales = metricas(items)
    return dict(
        **_meta(ahora, mes=desde.strftime("%Y-%m"), desde=desde.isoformat(), hasta=hasta.isoformat()),
        estado_periodo=_estado_periodo(desde, hasta, ahora), provisional=totales["provisionales"] > 0,
        totales=totales,
        graficos=dict(
            # Torta / barras de estados: solo lo ya realizado (las futuras no son ausencias).
            estados=[dict(estado=e, cantidad=totales[k]) for e, k in (
                ("presente", "presentes"), ("tarde", "tarde"), ("ausente", "ausentes"),
                ("ausente_provisional", "ausentes_provisionales"), ("justificado", "justificados"))],
            # Horas: plan completo del mes, lo realizado, lo asistido y lo que falta por hacer (no incumplido).
            minutos=dict(planificados=totales["minutos_planificados"], realizados=totales["minutos_realizados"],
                         asistidos=totales["minutos_asistidos"],
                         por_realizar=totales["minutos_planificados"] - totales["minutos_realizados"]),
        ),
        por_reunion=_por_reunion(items), definiciones=DEFINICIONES,
    )


def _meses(desde, hasta):
    actual = desde
    while actual <= hasta:
        yield actual
        actual = (actual.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def evolucion(empleado, desde_mes=None, hasta_mes=None, *, ahora=None):
    """Serie mensual (hasta 12 meses, incluidos los meses sin actividad) con las mismas metricas del dashboard."""
    ahora = ahora or now_local()
    hasta = mes_param(hasta_mes, "hasta_mes")[0] if hasta_mes else ahora.date().replace(day=1)
    if desde_mes:
        desde = mes_param(desde_mes, "desde_mes")[0]
    else:
        desde = hasta
        for _ in range(5):  # por defecto, 6 meses
            desde = (desde - dt.timedelta(days=1)).replace(day=1)
    if desde > hasta:
        raise Error("'desde_mes' no puede ser posterior a 'hasta_mes'.")
    meses = list(_meses(desde, hasta))
    if len(meses) > EVOLUCION_MAX_MESES:
        raise Error(f"El rango máximo es de {EVOLUCION_MAX_MESES} meses.")
    ultimo = dt.date(hasta.year, hasta.month, calendar.monthrange(hasta.year, hasta.month)[1])
    with db.transaction(read_only=True) as c:
        items = ocurrencias_empleado(c, empleado, desde, ultimo, ahora)
    serie = []
    for inicio_mes in meses:
        clave = inicio_mes.strftime("%Y-%m")
        del_mes = [i for i in items if i["fecha"].startswith(clave)]
        fin_mes = dt.date(inicio_mes.year, inicio_mes.month, calendar.monthrange(inicio_mes.year, inicio_mes.month)[1])
        serie.append(dict(mes=clave, estado_periodo=_estado_periodo(inicio_mes, fin_mes, ahora), **metricas(del_mes)))
    return dict(
        **_meta(ahora, desde_mes=desde.strftime("%Y-%m"), hasta_mes=hasta.strftime("%Y-%m"),
                desde=desde.isoformat(), hasta=ultimo.isoformat()),
        limites=dict(max_meses=EVOLUCION_MAX_MESES), meses=serie, totales=metricas(items),
        por_reunion=_por_reunion(items), definiciones=DEFINICIONES,
    )


def proximas_ocurrencias(empleado, reunion_id, *, dias=60, limite=6, ahora=None):
    """Para el detalle de una reunion: sus proximas ocurrencias no canceladas (mismas reglas que el calendario)."""
    ahora = ahora or now_local()
    with db.transaction(read_only=True) as c:
        items = ocurrencias_empleado(c, empleado, ahora.date(), ahora.date() + dt.timedelta(days=dias), ahora)
    return [i for i in items if i["reunion_id"] == int(reunion_id) and i["estado"] in ESTADOS_PROXIMA][:limite]


def historial_empleado(empleado, *, desde=None, hasta=None, reunion_id=None, page=1, per_page=20):
    where, args = ["a.empleado_id=%s"], [empleado["id"]]
    if desde:
        where.append("a.fecha >= %s")
        args.append(desde)
    if hasta:
        where.append("a.fecha <= %s")
        args.append(hasta)
    if reunion_id:
        where.append("a.reunion_id=%s")
        args.append(int(reunion_id))
    clause = " AND ".join(where)
    with db.transaction(read_only=True) as c:
        total = db.one(c, f"SELECT COUNT(*) AS n FROM reunion_asistencias a WHERE {clause}", tuple(args))["n"]
        rows = db.all_rows(c, f"""SELECT a.id, a.reunion_id, r.nombre, COALESCE(rs.lugar, r.lugar) AS lugar,
                                         a.sucursal_id, su.nombre AS sucursal_nombre, a.fecha, o.fecha_original, o.inicio, o.fin,
                                         o.estado AS estado_ocurrencia, a.estado, a.registrado_at, a.metodo, a.observaciones
                                  FROM reunion_asistencias a JOIN reuniones r ON r.id=a.reunion_id
                                  JOIN reunion_ocurrencias o ON o.id=a.ocurrencia_id
                                  LEFT JOIN reunion_sedes rs ON rs.reunion_id=a.reunion_id AND rs.sucursal_id=a.sucursal_id
                                  LEFT JOIN sucursales su ON su.id=a.sucursal_id
                                  WHERE {clause} ORDER BY a.fecha DESC, o.inicio DESC LIMIT %s OFFSET %s""",
                           (*args, per_page, (page - 1) * per_page))
    items = [dict(id=row["id"], reunion_id=row["reunion_id"], nombre=row["nombre"], lugar=row["lugar"],
                  sucursal_id=row["sucursal_id"] or None, sucursal_nombre=row["sucursal_nombre"],
                  fecha=_iso(row["fecha"]), fecha_original=_iso(row["fecha_original"]),
                  inicio=_hhmm(row["inicio"]), fin=_hhmm(row["fin"]),
                  estado="cancelada" if row["estado_ocurrencia"] == "cancelada" else row["estado"],
                  registrado_at=_iso(row["registrado_at"]), metodo=row["metodo"], observaciones=row["observaciones"])
             for row in rows]
    return dict(items=items, page=page, per_page=per_page, total=int(total))


def estadisticas_empleado(empleado, desde, hasta):
    with db.transaction(read_only=True) as c:
        sql, params = _agregado("a.empleado_id=%s AND a.fecha BETWEEN %s AND %s", (empleado["id"], desde, hasta))
        total = _tasas(db.one(c, sql, params))
        por_reunion = _agrupado(c, "a.empleado_id=%s AND a.fecha BETWEEN %s AND %s", (empleado["id"], desde, hasta),
                                "a.reunion_id, r.nombre AS nombre", "JOIN reuniones r ON r.id = a.reunion_id")
    por_reunion.sort(key=lambda x: x["nombre"])
    return dict(periodo=dict(desde=_iso(desde), hasta=_iso(hasta)), totales=total, por_reunion=por_reunion)
