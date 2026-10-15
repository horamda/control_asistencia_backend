"""Reuniones: recurrencia, convocados, QR fijo/dinamico, asistencia y estadisticas.

Cada fecha en que ocurre una reunion se guarda en reunion_ocurrencias con su horario
congelado: editar la reunion no altera el historial. Al terminar la ventana de registro,
el cierre (scheduler) marca ausentes a los convocados sin registro y justifica a quienes
estaban de vacaciones o franco."""

import calendar
import datetime as dt
import logging
from urllib.parse import parse_qs, urlparse

import jwt
from mysql.connector import IntegrityError

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local
from utils.jwt import _get_secret

logger = logging.getLogger(__name__)

FRECUENCIAS = ("diaria", "semanal", "mensual")
QR_MODOS = ("fijo", "dinamico", "ambos")
ESTADOS = ("presente", "tarde", "ausente", "justificado")
QR_PREFIX = "fichaya://reunion?t="
QR_TIPO = "reunion_qr"
QR_DINAMICO_TTL = 45
QR_FIJO_TTL = 10 * 365 * 24 * 3600
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
SEMANAS = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "último"}
MAX_RANGO_DIAS = 366


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


def pct(parte, total):
    return round(parte * 100.0 / total, 1) if total else None


# --- Recurrencia ---------------------------------------------------------------------

def ocurre_en(r, fecha):
    """True si la reunion r (dict de la tabla) ocurre en la fecha dada."""
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


def fechas(r, desde, hasta):
    if (hasta - desde).days > MAX_RANGO_DIAS:
        hasta = desde + dt.timedelta(days=MAX_RANGO_DIAS)
    dia = desde
    while dia <= hasta:
        if ocurre_en(r, dia):
            yield dia
        dia += dt.timedelta(days=1)


def proxima_fecha(r, desde=None, dias=MAX_RANGO_DIAS):
    desde = desde or now_local().date()
    return next(fechas(r, desde, desde + dt.timedelta(days=dias)), None)


def horarios(r, fecha):
    """Momentos de la ocurrencia: inicio, fin y ventana de registro."""
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


def describir(r):
    hora = _hhmm(_time(r["hora_inicio"]))
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


def convocados(c, reunion):
    return db.all_rows(
        c,
        f"""SELECT e.id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre
            FROM empleados e LEFT JOIN sectores s ON s.id = e.sector_id
            WHERE e.empresa_id = %s AND e.activo = 1
              AND EXISTS (SELECT 1 FROM reunion_participantes p WHERE p.reunion_id = %s AND {_REGLA_EMPLEADO})
            ORDER BY e.apellido, e.nombre""",
        (reunion["empresa_id"], reunion["id"]),
    )


def contar_convocados(c, empresa_id):
    rows = db.all_rows(
        c,
        f"""SELECT r.id, COUNT(e.id) AS n FROM reuniones r
            JOIN empleados e ON e.empresa_id = r.empresa_id AND e.activo = 1
            WHERE r.empresa_id = %s
              AND EXISTS (SELECT 1 FROM reunion_participantes p WHERE p.reunion_id = r.id AND {_REGLA_EMPLEADO})
            GROUP BY r.id""",
        (empresa_id,),
    )
    return {row["id"]: int(row["n"]) for row in rows}


def reuniones_de_empleado(c, empleado, reunion_id=None, solo_activas=True):
    sql = f"""SELECT r.* FROM reuniones r JOIN empleados e ON e.id = %s
              WHERE r.empresa_id = e.empresa_id
                AND EXISTS (SELECT 1 FROM reunion_participantes p WHERE p.reunion_id = r.id AND {_REGLA_EMPLEADO})"""
    args = [empleado["id"]]
    if solo_activas:
        sql += " AND r.activa = 1"
    if reunion_id:
        sql += " AND r.id = %s"
        args.append(int(reunion_id))
    return db.all_rows(c, sql + " ORDER BY r.hora_inicio, r.nombre", tuple(args))


# --- Ocurrencias -----------------------------------------------------------------------

def ocurrencia(c, r, fecha, crear=True, lock=False):
    """Fila de la ocurrencia (creandola con el horario actual si no existe)."""
    sql = "SELECT * FROM reunion_ocurrencias WHERE reunion_id = %s AND fecha = %s" + (" FOR UPDATE" if lock else "")
    row = db.one(c, sql, (r["id"], fecha))
    if row or not crear:
        return row
    h = horarios(r, fecha)
    c.execute(
        """INSERT IGNORE INTO reunion_ocurrencias
           (empresa_id, reunion_id, fecha, inicio, fin, ventana_desde, ventana_hasta, tarde_desde, estado)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'programada')""",
        (r["empresa_id"], r["id"], fecha, h["inicio"], h["fin"], h["ventana_desde"], h["ventana_hasta"], h["tarde_desde"]),
    )
    return db.one(c, sql, (r["id"], fecha))


def _justificacion_automatica(c, empleado_ids, fecha):
    if not empleado_ids:
        return {}
    marcas = ", ".join(["%s"] * len(empleado_ids))
    motivos = {}
    for row in db.all_rows(c, f"SELECT empleado_id FROM vacaciones WHERE empleado_id IN ({marcas})"
                              " AND fecha_desde <= %s AND fecha_hasta >= %s", (*empleado_ids, fecha, fecha)):
        motivos[row["empleado_id"]] = "Vacaciones"
    for row in db.all_rows(c, f"SELECT empleado_id FROM francos WHERE empleado_id IN ({marcas}) AND fecha = %s",
                           (*empleado_ids, fecha)):
        motivos.setdefault(row["empleado_id"], "Franco")
    return motivos


def cerrar_ocurrencias(*, ahora=None, dias_atras=7):
    """Cierra las ocurrencias cuya ventana de registro termino. Idempotente."""
    ahora = ahora or now_local()
    with db.transaction(read_only=True) as c:
        reuniones = db.all_rows(c, "SELECT * FROM reuniones WHERE activa = 1")
    resumen = dict(cerradas=0, ausentes=0, justificados=0, errores=0)
    for r in reuniones:
        creada = r.get("created_at")
        for fecha in fechas(r, ahora.date() - dt.timedelta(days=dias_atras), ahora.date()):
            h = horarios(r, fecha)
            if h["ventana_hasta"] > ahora or (creada and h["inicio"] < creada):
                continue
            try:
                with db.transaction() as c:
                    occ = ocurrencia(c, r, fecha, lock=True)
                    if occ["estado"] != "programada" or occ["ventana_hasta"] > ahora:
                        continue
                    lista = convocados(c, r)
                    registrados = {row["empleado_id"] for row in db.all_rows(
                        c, "SELECT empleado_id FROM reunion_asistencias WHERE ocurrencia_id = %s", (occ["id"],))}
                    faltan = [e["id"] for e in lista if e["id"] not in registrados]
                    motivos = _justificacion_automatica(c, faltan, fecha)
                    for empleado_id in faltan:
                        motivo = motivos.get(empleado_id)
                        db.insert(c, "reunion_asistencias", dict(
                            empresa_id=r["empresa_id"], reunion_id=r["id"], ocurrencia_id=occ["id"],
                            empleado_id=empleado_id, fecha=fecha, estado="justificado" if motivo else "ausente",
                            metodo="sistema", observaciones=motivo, updated_at=ahora))
                        resumen["justificados" if motivo else "ausentes"] += 1
                    total = len(registrados | {e["id"] for e in lista})
                    c.execute("UPDATE reunion_ocurrencias SET estado='cerrada', convocados=%s, cerrada_at=%s WHERE id=%s",
                              (total, ahora, occ["id"]))
                    resumen["cerradas"] += 1
            except Exception:
                logger.exception("reunion_cierre_error", extra={"extra": {"reunion_id": r["id"], "fecha": str(fecha)}})
                resumen["errores"] += 1
    if resumen["cerradas"] or resumen["errores"]:
        logger.info("reuniones_cierre", extra={"extra": resumen})
    return resumen


# --- QR ------------------------------------------------------------------------------

def _token(payload, ttl):
    data = dict(payload, type=QR_TIPO, exp=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=ttl))
    return jwt.encode(data, _get_secret(), algorithm="HS256")


def qr_fijo(r):
    return QR_PREFIX + _token({"rid": r["id"], "emp": r["empresa_id"], "m": "fijo", "v": int(r["qr_version"])}, QR_FIJO_TTL)


def qr_dinamico(r, fecha):
    return QR_PREFIX + _token({"rid": r["id"], "emp": r["empresa_id"], "m": "dinamico", "f": fecha.isoformat()},
                              QR_DINAMICO_TTL)


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
        reunion_id=r["id"], reunion=r["nombre"], lugar=r.get("lugar"), fecha=_iso(occ["fecha"]),
        inicio=_hhmm(occ["inicio"]), fin=_hhmm(occ["fin"]), estado=row["estado"],
        registrado_at=_iso(row.get("registrado_at")), ya_registrado=ya_registrado,
    )


def registrar_qr(empleado, contenido, *, lat=None, lon=None, ahora=None):
    """Registra la asistencia del empleado autenticado a partir del QR escaneado."""
    ahora = ahora or now_local()
    payload = _leer_qr(contenido)
    if int(payload.get("emp") or 0) != int(empleado["empresa_id"]):
        raise Error("Este QR pertenece a otra empresa.", 403)
    with db.transaction() as c:
        r = db.one(c, "SELECT * FROM reuniones WHERE id = %s AND empresa_id = %s", (payload["rid"], empleado["empresa_id"]))
        if not r or not r["activa"]:
            raise Error("La reunión no existe o está desactivada.", 404)
        modo = payload.get("m")
        if modo == "fijo" and (r["qr_modo"] == "dinamico" or int(payload.get("v") or 0) != int(r["qr_version"])):
            raise Error("Este QR impreso ya no es válido. Pedí el QR actualizado al organizador.", 409)
        if modo == "dinamico" and r["qr_modo"] == "fijo":
            raise Error("Esta reunión se registra con el QR impreso.", 409)
        if not reuniones_de_empleado(c, empleado, r["id"]):
            raise Error("No estás convocado a esta reunión.", 403)
        fecha = ahora.date()
        if modo == "dinamico" and payload.get("f") != fecha.isoformat():
            raise Error("El QR corresponde a otra fecha.", 409)
        existente = ocurrencia(c, r, fecha, crear=False, lock=True)
        if not existente and not ocurre_en(r, fecha):
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
        if previo:
            c.execute("UPDATE reunion_asistencias SET estado=%s, registrado_at=%s, metodo=%s, lat=%s, lon=%s, updated_at=%s"
                      " WHERE id=%s", (*datos.values(), previo["id"]))
        else:
            try:
                db.insert(c, "reunion_asistencias", dict(
                    empresa_id=r["empresa_id"], reunion_id=r["id"], ocurrencia_id=occ["id"], empleado_id=empleado["id"],
                    fecha=fecha, **datos))
            except IntegrityError:  # doble escaneo simultaneo
                previo = db.one(c, "SELECT * FROM reunion_asistencias WHERE ocurrencia_id = %s AND empleado_id = %s",
                                (occ["id"], empleado["id"]))
                return _registro_dict(r, occ, previo, True)
        return _registro_dict(r, occ, dict(estado=estado, registrado_at=ahora), False)


def marcar_manual(who, reunion_id, fecha, empleado_id, estado, observaciones=None, *, ahora=None):
    """Carga o corrige la asistencia desde el panel (presente, tarde, ausente o justificado)."""
    if estado not in ESTADOS:
        raise Error("Estado inválido.")
    ahora = ahora or now_local()
    fecha = _date(fecha)
    if fecha > ahora.date():
        raise Error("No se puede cargar asistencia de una fecha futura.")
    with db.transaction() as c:
        r = obtener(c, who, reunion_id)
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
                empresa_id=r["empresa_id"], reunion_id=r["id"], ocurrencia_id=occ["id"], empleado_id=empleado["id"],
                fecha=fecha, estado=estado, registrado_at=registrado, metodo="manual", usuario_id=who.get("user_id"),
                observaciones=obs, updated_at=ahora))


def cancelar_ocurrencia(who, reunion_id, fecha, motivo, *, cancelar=True):
    fecha = _date(fecha)
    with db.transaction() as c:
        r = obtener(c, who, reunion_id)
        if not ocurre_en(r, fecha) and not ocurrencia(c, r, fecha, crear=False):
            raise Error("La reunión no ocurre en esa fecha.")
        occ = ocurrencia(c, r, fecha, lock=True)
        if cancelar:
            motivo = (motivo or "").strip()[:255]
            if not motivo:
                raise Error("Indicá el motivo de la cancelación.")
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
    try:
        hora = _time(str(data.get("hora_inicio") or ""))
    except (ValueError, TypeError):
        raise Error("Hora de inicio inválida (HH:MM).")
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
    out["activa"] = 0 if str(data.get("activa", "1")) == "0" else 1
    return out


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
            c, f"SELECT id FROM empleados WHERE empresa_id=%s AND id IN ({', '.join(['%s'] * len(ids))})",
            (empresa_id, *ids))}
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
        if reunion_id:
            obtener(c, who, reunion_id, lock=True)
            sets = ", ".join(f"{k}=%s" for k in valores)
            c.execute(f"UPDATE reuniones SET {sets}, updated_at=%s WHERE id=%s", (*valores.values(), ahora, reunion_id))
            c.execute("DELETE FROM reunion_participantes WHERE reunion_id=%s", (reunion_id,))
            # Las ocurrencias futuras sin registros toman el horario nuevo.
            c.execute("""DELETE o FROM reunion_ocurrencias o WHERE o.reunion_id=%s AND o.estado='programada'
                         AND o.inicio > %s AND NOT EXISTS (SELECT 1 FROM reunion_asistencias a WHERE a.ocurrencia_id=o.id)""",
                      (reunion_id, ahora))
        else:
            reunion_id = db.insert(c, "reuniones", dict(valores, empresa_id=who["empresa_id"], creado_por=who.get("user_id"),
                                                         qr_version=1, created_at=ahora, updated_at=ahora))
        for empleado_id, sector_id, puesto_id in sorted(reglas_nuevas, key=str):
            db.insert(c, "reunion_participantes", dict(reunion_id=reunion_id, empleado_id=empleado_id,
                                                        sector_id=sector_id, puesto_id=puesto_id))
    return reunion_id


def eliminar(who, reunion_id):
    """Elimina la reunion si no tiene asistencias; con historial solo se puede desactivar."""
    with db.transaction() as c:
        obtener(c, who, reunion_id, lock=True)
        if db.one(c, "SELECT 1 AS x FROM reunion_asistencias WHERE reunion_id=%s LIMIT 1", (reunion_id,)):
            raise Error("La reunión tiene asistencias registradas: desactivala para conservar las estadísticas.", 409)
        c.execute("DELETE FROM reuniones WHERE id=%s", (reunion_id,))


def regenerar_qr(who, reunion_id):
    with db.transaction() as c:
        obtener(c, who, reunion_id, lock=True)
        c.execute("UPDATE reuniones SET qr_version = qr_version + 1, updated_at=%s WHERE id=%s", (now_local(), reunion_id))


# --- Consultas del panel -------------------------------------------------------------------

def _agregado(where, args):
    return f"""SELECT COUNT(*) AS convocatorias,
                      COALESCE(SUM(a.estado='presente'),0) AS presentes,
                      COALESCE(SUM(a.estado='tarde'),0) AS tarde,
                      COALESCE(SUM(a.estado='ausente'),0) AS ausentes,
                      COALESCE(SUM(a.estado='justificado'),0) AS justificados
               FROM reunion_asistencias a JOIN reunion_ocurrencias o ON o.id = a.ocurrencia_id
               WHERE o.estado <> 'cancelada' AND {where}""", args


def _tasas(row):
    row = {k: int(v or 0) if k in ("convocatorias", "presentes", "tarde", "ausentes", "justificados") else v
           for k, v in row.items()}
    asistidas = row["presentes"] + row["tarde"]
    row["asistidas"] = asistidas
    row["asistencia_pct"] = pct(asistidas, row["convocatorias"] - row["justificados"])
    row["puntualidad_pct"] = pct(row["presentes"], asistidas)
    return row


def listado(who, *, q=None, estado=None, desde=None, hasta=None):
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
    with db.transaction(read_only=True) as c:
        rows = db.all_rows(c, f"SELECT r.* FROM reuniones r WHERE {' AND '.join(where)} ORDER BY r.activa DESC, r.nombre",
                           tuple(args))
        cantidades = contar_convocados(c, who["empresa_id"])
        sql, params = _agregado("a.empresa_id=%s AND a.fecha BETWEEN %s AND %s GROUP BY a.reunion_id",
                                (who["empresa_id"], desde, hasta))
        stats = {row["reunion_id"]: _tasas(row) for row in db.all_rows(
            c, sql.replace("SELECT COUNT(*)", "SELECT a.reunion_id, COUNT(*)"), params)}
        hoy = db.all_rows(c, "SELECT reunion_id, estado FROM reunion_ocurrencias WHERE empresa_id=%s AND fecha=%s",
                          (who["empresa_id"], ahora.date()))
    canceladas_hoy = {row["reunion_id"] for row in hoy if row["estado"] == "cancelada"}
    for r in rows:
        r["descripcion_frecuencia"] = describir(r)
        r["convocados"] = cantidades.get(r["id"], 0)
        r["proxima"] = proxima_fecha(r) if r["activa"] else None
        r["stats"] = stats.get(r["id"])
        r["hoy"] = r["activa"] and ocurre_en(r, ahora.date()) and r["id"] not in canceladas_hoy
    total = _tasas(dict(convocatorias=sum(s["convocatorias"] for s in stats.values()),
                        presentes=sum(s["presentes"] for s in stats.values()),
                        tarde=sum(s["tarde"] for s in stats.values()),
                        ausentes=sum(s["ausentes"] for s in stats.values()),
                        justificados=sum(s["justificados"] for s in stats.values())))
    return dict(reuniones=rows, total=total, desde=desde, hasta=hasta)


def detalle(who, reunion_id, *, desde=None, hasta=None):
    ahora = now_local()
    hasta = hasta or ahora.date()
    desde = desde or hasta - dt.timedelta(days=89)
    with db.transaction(read_only=True) as c:
        r = obtener(c, who, reunion_id)
        lista = convocados(c, r)
        r["reglas"] = reglas(c, r["id"])
        ocurrencias = db.all_rows(c, """
            SELECT o.*, COUNT(a.id) AS convocatorias,
                   COALESCE(SUM(a.estado='presente'),0) AS presentes, COALESCE(SUM(a.estado='tarde'),0) AS tarde,
                   COALESCE(SUM(a.estado='ausente'),0) AS ausentes, COALESCE(SUM(a.estado='justificado'),0) AS justificados
            FROM reunion_ocurrencias o LEFT JOIN reunion_asistencias a ON a.ocurrencia_id = o.id
            WHERE o.reunion_id=%s AND o.fecha BETWEEN %s AND %s
            GROUP BY o.id ORDER BY o.fecha DESC""", (r["id"], desde, hasta))
        sql, params = _agregado("a.reunion_id=%s AND a.fecha BETWEEN %s AND %s GROUP BY a.empleado_id",
                                (r["id"], desde, hasta))
        por_empleado = {row["empleado_id"]: _tasas(row) for row in db.all_rows(
            c, sql.replace("SELECT COUNT(*)", "SELECT a.empleado_id, COUNT(*)"), params)}
        nombres = {row["id"]: row for row in db.all_rows(
            c, f"SELECT e.id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre FROM empleados e"
               f" LEFT JOIN sectores s ON s.id=e.sector_id WHERE e.id IN ({', '.join(['%s'] * len(por_empleado)) or 'NULL'})",
            tuple(por_empleado))} if por_empleado else {}
    for o in ocurrencias:
        o.update(_tasas({k: o[k] for k in ("convocatorias", "presentes", "tarde", "ausentes", "justificados")}))
        if o["estado"] == "programada" and o["convocados"] is None:
            o["convocados"] = len(lista)
    ranking = []
    for empleado_id, s in por_empleado.items():
        e = nombres.get(empleado_id) or {"apellido": f"#{empleado_id}", "nombre": "", "legajo": None, "sector_nombre": None}
        ranking.append(dict(s, empleado_id=empleado_id, **{k: e.get(k) for k in ("apellido", "nombre", "legajo", "sector_nombre")}))
    ranking.sort(key=lambda x: (x["asistencia_pct"] is None, x["asistencia_pct"] or 0, x["apellido"] or ""))
    r["descripcion_frecuencia"] = describir(r)
    total = _tasas(dict(convocatorias=sum(s["convocatorias"] for s in por_empleado.values()),
                        presentes=sum(s["presentes"] for s in por_empleado.values()),
                        tarde=sum(s["tarde"] for s in por_empleado.values()),
                        ausentes=sum(s["ausentes"] for s in por_empleado.values()),
                        justificados=sum(s["justificados"] for s in por_empleado.values())))
    proximas = list(fechas(r, ahora.date(), ahora.date() + dt.timedelta(days=60)))[:6] if r["activa"] else []
    return dict(reunion=r, convocados=lista, ocurrencias=ocurrencias, ranking=ranking, total=total,
                proximas=proximas, desde=desde, hasta=hasta)


def ocurrencia_detalle(who, reunion_id, fecha):
    fecha = _date(fecha)
    ahora = now_local()
    with db.transaction(read_only=True) as c:
        r = obtener(c, who, reunion_id)
        occ = ocurrencia(c, r, fecha, crear=False)
        if not occ and not ocurre_en(r, fecha):
            raise Error("La reunión no ocurre en esa fecha.", 404)
        registros = {row["empleado_id"]: row for row in db.all_rows(
            c, "SELECT * FROM reunion_asistencias WHERE ocurrencia_id=%s", (occ["id"],))} if occ else {}
        lista = convocados(c, r)
        extra = set(registros) - {e["id"] for e in lista}
        if extra:  # registrados que ya no estan convocados (o inactivos): se muestran igual
            lista += db.all_rows(c, f"SELECT e.id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre FROM empleados e"
                                    f" LEFT JOIN sectores s ON s.id=e.sector_id WHERE e.id IN ({', '.join(['%s'] * len(extra))})",
                                 tuple(extra))
    h = occ or horarios(r, fecha)
    filas = []
    for e in lista:
        reg = registros.get(e["id"])
        filas.append(dict(e, estado=reg["estado"] if reg else "pendiente", registrado_at=reg["registrado_at"] if reg else None,
                          metodo=reg["metodo"] if reg else None, observaciones=reg["observaciones"] if reg else None))
    conteo = {k: sum(1 for f in filas if f["estado"] == k) for k in ESTADOS + ("pendiente",)}
    return dict(reunion=r, fecha=fecha, ocurrencia=occ, horario=h, filas=filas, conteo=conteo,
                abierta=h["ventana_desde"] <= ahora <= h["ventana_hasta"], futura=fecha > ahora.date())


def estadisticas_empresa(who, desde, hasta):
    """Resumen por reunion y por empleado (los de menor asistencia primero)."""
    with db.transaction(read_only=True) as c:
        sql, params = _agregado("a.empresa_id=%s AND a.fecha BETWEEN %s AND %s GROUP BY a.reunion_id, r.nombre",
                                (who["empresa_id"], desde, hasta))
        sql = sql.replace("SELECT COUNT(*)", "SELECT a.reunion_id, r.nombre, COUNT(*)").replace(
            "JOIN reunion_ocurrencias o", "JOIN reuniones r ON r.id = a.reunion_id JOIN reunion_ocurrencias o")
        por_reunion = [_tasas(row) for row in db.all_rows(c, sql, params)]
        sql, params = _agregado("a.empresa_id=%s AND a.fecha BETWEEN %s AND %s"
                                " GROUP BY a.empleado_id, e.apellido, e.nombre, e.legajo",
                                (who["empresa_id"], desde, hasta))
        sql = sql.replace("SELECT COUNT(*)", "SELECT a.empleado_id, e.apellido, e.nombre, e.legajo, COUNT(*)").replace(
            "JOIN reunion_ocurrencias o", "JOIN empleados e ON e.id = a.empleado_id JOIN reunion_ocurrencias o")
        por_empleado = [_tasas(row) for row in db.all_rows(c, sql, params)]
        serie = db.all_rows(c, """SELECT a.fecha, COUNT(*) AS convocatorias,
                COALESCE(SUM(a.estado IN ('presente','tarde')),0) AS asistidas, COALESCE(SUM(a.estado='justificado'),0) AS justificados
            FROM reunion_asistencias a JOIN reunion_ocurrencias o ON o.id=a.ocurrencia_id
            WHERE o.estado<>'cancelada' AND a.empresa_id=%s AND a.fecha BETWEEN %s AND %s GROUP BY a.fecha ORDER BY a.fecha""",
                            (who["empresa_id"], desde, hasta))
    por_reunion.sort(key=lambda x: (x["asistencia_pct"] is None, x["asistencia_pct"] or 0))
    por_empleado.sort(key=lambda x: (x["asistencia_pct"] is None, x["asistencia_pct"] or 0, x["apellido"] or ""))
    for row in serie:
        row["asistencia_pct"] = pct(int(row["asistidas"]), int(row["convocatorias"]) - int(row["justificados"]))
    total = _tasas({k: sum(x[k] for x in por_reunion) for k in ("convocatorias", "presentes", "tarde", "ausentes", "justificados")})
    return dict(por_reunion=por_reunion, por_empleado=por_empleado, serie=serie, total=total)


# --- API del empleado ------------------------------------------------------------------------

def reunion_publica(r):
    return dict(
        id=r["id"], nombre=r["nombre"], descripcion=r.get("descripcion"), lugar=r.get("lugar"),
        frecuencia=r["frecuencia"], dias_semana=_dias(r.get("dias_semana")), mensual_tipo=r.get("mensual_tipo"),
        dia_mes=r.get("dia_mes"), semana_mes=r.get("semana_mes"), hora_inicio=_hhmm(_time(r["hora_inicio"])),
        duracion_min=int(r["duracion_min"]), descripcion_frecuencia=describir(r), qr_modo=r["qr_modo"],
        tolerancia_antes_min=int(r["tolerancia_antes_min"]), tarde_despues_min=int(r["tarde_despues_min"]),
        cierre_despues_min=r.get("cierre_despues_min"), fecha_inicio=_iso(_date(r["fecha_inicio"])),
        fecha_fin=_iso(_date(r["fecha_fin"])) if r.get("fecha_fin") else None,
    )


def mis_reuniones(empleado, *, ahora=None):
    ahora = ahora or now_local()
    with db.transaction(read_only=True) as c:
        rows = reuniones_de_empleado(c, empleado)
        sql, params = _agregado("a.empleado_id=%s GROUP BY a.reunion_id", (empleado["id"],))
        sql = sql.replace("SELECT COUNT(*)", "SELECT a.reunion_id, COUNT(*)")
        stats = {row["reunion_id"]: _tasas(row) for row in db.all_rows(c, sql, params)}
    items = []
    for r in rows:
        proxima = proxima_fecha(r, ahora.date())
        item = reunion_publica(r)
        item["proxima_fecha"] = _iso(proxima)
        item["mis_estadisticas"] = stats.get(r["id"]) or _tasas(dict(convocatorias=0, presentes=0, tarde=0, ausentes=0,
                                                                   justificados=0))
        items.append(item)
    return items


def proximas(empleado, dias=7, *, ahora=None):
    """Ocurrencias de hoy en adelante (incluye las de hoy ya pasadas) con el estado del empleado."""
    ahora = ahora or now_local()
    dias = max(1, min(int(dias or 7), 31))
    desde, hasta = ahora.date(), ahora.date() + dt.timedelta(days=dias - 1)
    with db.transaction(read_only=True) as c:
        rows = reuniones_de_empleado(c, empleado)
        guardadas = {(o["reunion_id"], o["fecha"]): o for o in db.all_rows(
            c, f"SELECT * FROM reunion_ocurrencias WHERE fecha BETWEEN %s AND %s AND reunion_id IN "
               f"({', '.join(['%s'] * len(rows)) or 'NULL'})", (desde, hasta, *[r["id"] for r in rows]))} if rows else {}
        mias = {row["ocurrencia_id"]: row for row in db.all_rows(
            c, "SELECT * FROM reunion_asistencias WHERE empleado_id=%s AND fecha BETWEEN %s AND %s",
            (empleado["id"], desde, hasta))}
    items = []
    for r in rows:
        for fecha in fechas(r, desde, hasta):
            occ = guardadas.get((r["id"], fecha))
            h = occ or horarios(r, fecha)
            reg = mias.get(occ["id"]) if occ else None
            if reg:
                estado = reg["estado"]
            elif occ and occ["estado"] == "cancelada":
                estado = "cancelada"
            elif ahora > h["ventana_hasta"]:
                estado = "ausente"
            elif ahora >= h["ventana_desde"]:
                estado = "abierta"
            else:
                estado = "pendiente"
            items.append(dict(
                reunion_id=r["id"], nombre=r["nombre"], lugar=r.get("lugar"), descripcion=r.get("descripcion"),
                fecha=fecha.isoformat(), inicio=_iso(h["inicio"]), fin=_iso(h["fin"]),
                ventana_desde=_iso(h["ventana_desde"]), ventana_hasta=_iso(h["ventana_hasta"]),
                tarde_desde=_iso(h["tarde_desde"]), estado=estado,
                cancelada=bool(occ and occ["estado"] == "cancelada"),
                motivo_cancelacion=occ.get("motivo_cancelacion") if occ else None,
                registrado_at=_iso(reg["registrado_at"]) if reg else None, qr_modo=r["qr_modo"],
            ))
    items.sort(key=lambda x: (x["inicio"], x["nombre"]))
    return dict(desde=desde.isoformat(), hasta=hasta.isoformat(), items=items)


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
        rows = db.all_rows(c, f"""SELECT a.id, a.reunion_id, r.nombre, r.lugar, a.fecha, o.inicio, o.fin, o.estado AS estado_ocurrencia,
                                         a.estado, a.registrado_at, a.metodo, a.observaciones
                                  FROM reunion_asistencias a JOIN reuniones r ON r.id=a.reunion_id
                                  JOIN reunion_ocurrencias o ON o.id=a.ocurrencia_id
                                  WHERE {clause} ORDER BY a.fecha DESC, o.inicio DESC LIMIT %s OFFSET %s""",
                           (*args, per_page, (page - 1) * per_page))
    items = [dict(id=row["id"], reunion_id=row["reunion_id"], nombre=row["nombre"], lugar=row["lugar"],
                  fecha=_iso(row["fecha"]), inicio=_hhmm(row["inicio"]), fin=_hhmm(row["fin"]),
                  estado="cancelada" if row["estado_ocurrencia"] == "cancelada" else row["estado"],
                  registrado_at=_iso(row["registrado_at"]), metodo=row["metodo"], observaciones=row["observaciones"])
             for row in rows]
    return dict(items=items, page=page, per_page=per_page, total=int(total))


def estadisticas_empleado(empleado, desde, hasta):
    with db.transaction(read_only=True) as c:
        sql, params = _agregado("a.empleado_id=%s AND a.fecha BETWEEN %s AND %s", (empleado["id"], desde, hasta))
        total = _tasas(db.one(c, sql, params))
        sql, params = _agregado("a.empleado_id=%s AND a.fecha BETWEEN %s AND %s GROUP BY a.reunion_id, r.nombre",
                                (empleado["id"], desde, hasta))
        sql = sql.replace("SELECT COUNT(*)", "SELECT a.reunion_id, r.nombre, COUNT(*)").replace(
            "JOIN reunion_ocurrencias o", "JOIN reuniones r ON r.id = a.reunion_id JOIN reunion_ocurrencias o")
        por_reunion = [_tasas(row) for row in db.all_rows(c, sql, params)]
    por_reunion.sort(key=lambda x: x["nombre"])
    return dict(periodo=dict(desde=_iso(desde), hasta=_iso(hasta)), totales=total, por_reunion=por_reunion)
