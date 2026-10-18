"""Vacaciones por semanas: lo que pide el empleado desde la app y lo que ve y resuelve su jefe.

Reglas (para todos los empleados; el panel de RR. HH. puede seguir cargando cualquier rango):
- Se piden semanas completas del calendario (lunes a domingo), corridas o no. Las semanas seguidas forman una tanda.
- Cada tanda empieza el lunes o, si es dia no laborable (calendario del panel: general, de la empresa o de la
  sucursal del empleado), el primer dia habil siguiente (LCT art. 151) y dura 7 dias corridos por semana: con el
  lunes feriado va de martes a lunes.
- El total no puede superar el saldo (dias disponibles menos lo pendiente). Lo que no llega a una semana completa lo
  carga RR. HH. desde el panel.
- Una tanda descuenta del anio en que empieza.
- El jefe ve las vacaciones de toda su cadena y aprueba a sus reportes directos. Un empleado sin jefe con reportes a
  cargo (los duenos) ve toda la empresa. Quien no tiene jefe ni reportes no ve a nadie.
- El empleado cancela lo pendiente; para dar de baja algo aprobado lo pide y lo resuelve su jefe o RR. HH."""

import datetime as dt
import logging
from decimal import Decimal

from repositories import carga_repository as db
from services import avisos_push, feriado_service
from services import vacaciones_service as vs
from services.carga_service import now_local

logger = logging.getLogger(__name__)

Error = vs.VacacionesError
SaldoError = vs.VacacionesSaldoInsuficienteError
DIAS_SEMANA = 7
MAX_SEMANAS = 10
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MENSAJE_SEMANAS = ("Las vacaciones se piden por semanas completas, de lunes a domingo. Si el lunes es feriado "
                   "empiezan el primer día hábil siguiente y duran los mismos 7 días.")


class NoEncontrada(Error):
    status = 404


class SinPermiso(Error):
    status = 403


class SesionInvalida(Error):
    status = 401


# --- Calendario -------------------------------------------------------------------------------------------

def _hoy():
    return now_local().date()


def _fecha(valor, nombre="fecha"):
    try:
        return vs._parse_date(valor, nombre)
    except Error:
        raise Error(f"{nombre} inválida (use AAAA-MM-DD).") from None


def _dia(fecha):
    return f"{DIAS[fecha.weekday()]} {fecha.strftime('%d/%m')}"


def es_habil(fecha, feriados):
    return fecha.weekday() < 5 and fecha not in feriados


def inicio_de_semana(lunes, feriados):
    """Primer dia habil de la semana (lunes o el siguiente habil si es feriado); None si no tiene ninguno."""
    for i in range(5):
        dia = lunes + dt.timedelta(days=i)
        if es_habil(dia, feriados):
            return dia
    return None


def _feriados(c, empleado):
    """{fecha: nombre} de los dias no laborables que aplican al empleado (general, empresa y su sucursal)."""
    return feriado_service.de_sucursal(feriado_service.mapa(c, empleado["empresa_id"]), empleado.get("sucursal_id") or 0)


def armar_tandas(semanas, feriados):
    """Lista de lunes -> tandas (semanas seguidas juntas) con inicio habil, fin, dias y anio."""
    if not isinstance(semanas, (list, tuple)) or not semanas:
        raise Error("Elegí al menos una semana.")
    lunes = []
    for valor in semanas:
        fecha = _fecha(valor, "semana")
        if fecha.weekday() != 0:
            raise Error(f"El {fecha.strftime('%d/%m/%Y')} no es lunes. {MENSAJE_SEMANAS}")
        lunes.append(fecha)
    if len(set(lunes)) != len(lunes):
        raise Error("Elegiste la misma semana dos veces.")
    if len(lunes) > MAX_SEMANAS:
        raise Error(f"Se pueden pedir hasta {MAX_SEMANAS} semanas por solicitud.")
    lunes.sort()
    grupos = [[lunes[0]]]
    for fecha in lunes[1:]:
        if fecha - grupos[-1][-1] == dt.timedelta(days=DIAS_SEMANA):
            grupos[-1].append(fecha)
        else:
            grupos.append([fecha])
    tandas = []
    for grupo in grupos:
        inicio = inicio_de_semana(grupo[0], feriados)
        if inicio is None:
            raise Error(f"La semana del {grupo[0].strftime('%d/%m')} no tiene días hábiles para empezar.")
        dias = DIAS_SEMANA * len(grupo)
        corridos = [grupo[0] + dt.timedelta(days=i) for i in range((inicio - grupo[0]).days)]
        tandas.append(dict(lunes=grupo[0], semanas=len(grupo), inicio=inicio, fin=inicio + dt.timedelta(days=dias - 1),
                           dias=dias, anio=inicio.year,
                           motivo_inicio=(f"Empieza el {_dia(inicio)} porque el {_dia(grupo[0])} es "
                                          f"{feriados.get(grupo[0]) or 'feriado'}.") if corridos else None))
    return tandas


# --- Empleados y cadena del jefe -------------------------------------------------------------------------

_COLUMNAS_EMPLEADO = """id, empresa_id, sucursal_id, sector_id, nombre, apellido, legajo, dni, reporta_a_empleado_id,
                        fecha_ingreso, fecha_baja, activo"""


def _empleado(c, empleado_id, *, lock=False):
    fila = db.one(c, f"SELECT {_COLUMNAS_EMPLEADO} FROM empleados WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                  (int(empleado_id),))
    if not fila or not fila["activo"]:
        raise SesionInvalida("Empleado no encontrado o inactivo.")
    return fila


def _nombre(fila):
    return " ".join(p for p in (str(fila.get("apellido") or "").strip(), str(fila.get("nombre") or "").strip()) if p)


def equipo(c, actor):
    """Quienes ve el actor: alcance equipo (toda su cadena), empresa (dueno: sin jefe y con reportes) o sin_equipo."""
    filas = db.all_rows(c, f"SELECT {_COLUMNAS_EMPLEADO} FROM empleados WHERE empresa_id = %s AND activo = 1",
                        (actor["empresa_id"],))
    por_id = {int(f["id"]): f for f in filas}
    hijos = {}
    for f in filas:
        if f["reporta_a_empleado_id"]:
            hijos.setdefault(int(f["reporta_a_empleado_id"]), []).append(int(f["id"]))
    yo = int(actor["id"])
    directos = set(hijos.get(yo, []))
    if not actor.get("reporta_a_empleado_id") and directos:
        alcance, visibles = "empresa", set(por_id) - {yo}
    else:
        visibles, pendientes = set(), list(directos)
        while pendientes:
            eid = pendientes.pop()
            if eid in visibles or eid == yo:
                continue  # sin ciclos
            visibles.add(eid)
            pendientes.extend(hijos.get(eid, []))
        alcance = "equipo" if visibles else "sin_equipo"
    return dict(alcance=alcance, visibles=visibles, directos=directos, empleados=por_id)


def en_cadena(c, actor, empleado_id):
    """True si el actor puede ver al empleado (lo usa el detalle de la bandeja de notificaciones)."""
    actor = db.one(c, f"SELECT {_COLUMNAS_EMPLEADO} FROM empleados WHERE id = %s", (int(actor["id"]),)) or actor
    return int(empleado_id) in equipo(c, actor)["visibles"]


# --- Solicitudes ----------------------------------------------------------------------------------------------

_SELECT_TANDAS = """SELECT vm.*, COALESCE(vm.solicitud_id, vm.id) AS sid, e.nombre, e.apellido, e.legajo,
                           e.reporta_a_empleado_id, r.nombre AS resolvio_nombre, r.apellido AS resolvio_apellido
                    FROM vacaciones_movimientos vm
                    JOIN empleados e ON e.id = vm.empleado_id
                    LEFT JOIN empleados r ON r.id = vm.resuelto_por_empleado_id
                    WHERE vm.tipo = 'tomado' AND vm.origen_movimiento_id IS NULL"""

_ESTADO_SOLICITUD = {"pendiente": "pendiente", "aprobado": "aprobada", "rechazado": "rechazada", "cancelada": "cancelada"}


def _estado_tanda(fila):
    return "cancelada" if fila.get("revertido_por_movimiento_id") else str(fila.get("estado") or "aprobado")


def _tanda(fila, hoy):
    estado = _estado_tanda(fila)
    desde, hasta = vs._parse_date(fila["fecha_desde"]), vs._parse_date(fila["fecha_hasta"])
    dias = int(Decimal(str(fila["dias"] or 0)))
    resolvio = None
    if fila.get("resuelto_por_empleado_id"):
        resolvio = _nombre(dict(nombre=fila.get("resolvio_nombre"), apellido=fila.get("resolvio_apellido")))
    elif fila.get("resuelto_by"):
        resolvio = "RR. HH."
    cancelacion = bool(fila.get("cancelacion_pedida_at")) and estado == "aprobado"
    return dict(
        movimiento_id=int(fila["id"]), fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat(), dias=dias,
        semanas=dias // DIAS_SEMANA if dias % DIAS_SEMANA == 0 else None, anio=int(fila["anio"]), estado=estado,
        inicio_corrido=desde.weekday() != 0 and dias % DIAS_SEMANA == 0, empezo=desde <= hoy,
        motivo_resolucion=fila.get("motivo_resolucion"), resuelto_por=resolvio,
        resuelto_at=vs._to_date_str(fila.get("resuelto_at")), cancelacion_pedida=cancelacion,
        cancelacion_motivo=fila.get("cancelacion_motivo") if cancelacion else None,
    )


def _agrupar(filas, hoy, *, actor_id=None, directos=()):
    grupos = {}
    for fila in filas:
        grupos.setdefault(int(fila["sid"]), []).append(fila)
    salida = []
    for sid, lista in grupos.items():
        lista.sort(key=lambda f: vs._parse_date(f["fecha_desde"]))
        tandas = [_tanda(f, hoy) for f in lista]
        estados = {t["estado"] for t in tandas}
        estado = _ESTADO_SOLICITUD.get(estados.pop()) if len(estados) == 1 else "parcial"
        empleado_id = int(lista[0]["empleado_id"])
        pendiente = any(t["estado"] == "pendiente" for t in tandas)
        cancelacion = any(t["cancelacion_pedida"] for t in tandas)
        salida.append(dict(
            id=sid, empleado=dict(id=empleado_id, nombre=_nombre(lista[0]), legajo=lista[0].get("legajo")),
            estado=estado, dias=sum(t["dias"] for t in tandas if t["estado"] in ("pendiente", "aprobado")),
            creado_at=vs._to_date_str(min(f["created_at"] for f in lista)) if lista[0].get("created_at") else None,
            observacion=lista[0].get("observacion"), tandas=tandas, pendiente=pendiente, cancelacion_pedida=cancelacion,
            puede_cancelar=actor_id == empleado_id and any(
                t["estado"] == "pendiente" or (t["estado"] == "aprobado" and not t["empezo"] and not t["cancelacion_pedida"])
                for t in tandas),
            puede_resolver=empleado_id in directos and pendiente,
            puede_resolver_cancelacion=empleado_id in directos and cancelacion,
        ))
    salida.sort(key=lambda s: (s["tandas"][0]["fecha_desde"], s["id"]))
    return salida


def _solicitudes(c, donde, args, hoy, **kw):
    return _agrupar(db.all_rows(c, f"{_SELECT_TANDAS} AND {donde} ORDER BY vm.fecha_desde, vm.id", tuple(args)), hoy, **kw)


def _solicitud(c, sid, hoy, **kw):
    lista = _solicitudes(c, "COALESCE(vm.solicitud_id, vm.id) = %s", (int(sid),), hoy, **kw)
    if not lista:
        raise NoEncontrada("Solicitud no encontrada.")
    return lista[0]


def _solapa(c, empleado_id, desde, hasta):
    return db.one(c, """SELECT id, fecha_desde, fecha_hasta FROM vacaciones_movimientos
                        WHERE empleado_id = %s AND tipo = 'tomado' AND estado IN ('pendiente', 'aprobado')
                          AND revertido_por_movimiento_id IS NULL AND origen_movimiento_id IS NULL
                          AND fecha_desde <= %s AND fecha_hasta >= %s LIMIT 1""", (int(empleado_id), hasta, desde))


def crear_solicitud(empleado_id, semanas, observacion=None):
    """Una solicitud con una tanda por grupo de semanas seguidas, en una sola transaccion. Avisa al jefe."""
    observacion = (str(observacion or "").strip() or None)
    observacion = observacion[:255] if observacion else None
    hoy = _hoy()
    with db.transaction() as c:
        empleado = _empleado(c, empleado_id, lock=True)  # serializa dos pedidos simultaneos del mismo empleado
        tandas = armar_tandas(semanas, _feriados(c, empleado))
        for t in tandas:
            if t["inicio"] <= hoy:
                raise Error(f"La semana del {t['lunes'].strftime('%d/%m')} ya empezó o pasó: elegí semanas futuras.")
            otra = _solapa(c, empleado["id"], t["inicio"], t["fin"])
            if otra:
                raise Error(f"Se superpone con vacaciones ya pedidas o aprobadas (del {vs._parse_date(otra['fecha_desde']):%d/%m} "
                            f"al {vs._parse_date(otra['fecha_hasta']):%d/%m}). Si son semanas seguidas, pedilas juntas.")
        for anio in sorted({t["anio"] for t in tandas}):
            pedidos = sum(t["dias"] for t in tandas if t["anio"] == anio)
            disponibles = Decimal(str(vs.calcular_resumen_vacaciones(int(empleado["id"]), anio)["vacaciones"]
                                      ["dias_disponibles_con_pendientes"] or 0))
            if pedidos > disponibles:
                semanas_disponibles = max(0, int(disponibles // DIAS_SEMANA))
                raise SaldoError(f"Saldo de vacaciones {anio} insuficiente: te quedan {vs._days_number(disponibles)} días "
                                 f"({semanas_disponibles} semana{'s' if semanas_disponibles != 1 else ''} completa"
                                 f"{'s' if semanas_disponibles != 1 else ''}) y pediste {pedidos}.")
        ids = []
        for t in tandas:
            ids.append(db.insert(c, "vacaciones_movimientos", dict(
                empleado_id=int(empleado["id"]), empresa_id=int(empleado["empresa_id"]), anio=t["anio"], tipo="tomado",
                dias=t["dias"], observacion=observacion, fecha_desde=t["inicio"].isoformat(),
                fecha_hasta=t["fin"].isoformat(), estado="pendiente")))
        sid = ids[0]
        c.execute(f"UPDATE vacaciones_movimientos SET solicitud_id = %s WHERE id IN ({db_marcas(ids)})", (sid, *ids))
        solicitud = _solicitud(c, sid, hoy, actor_id=int(empleado["id"]))
    avisos_push.revision_vacaciones_solicitud(sid)
    return solicitud


def db_marcas(valores):
    return ", ".join(["%s"] * len(valores))


def semanas_de_rango(empleado_id, fecha_desde, fecha_hasta):
    """Compatibilidad con los endpoints por fechas: el rango tiene que ser semanas completas (con el inicio corrido
    si el lunes es feriado). Devuelve los lunes."""
    desde, hasta = _fecha(fecha_desde, "fecha_desde"), _fecha(fecha_hasta, "fecha_hasta")
    if desde > hasta:
        raise Error("fecha_desde no puede ser posterior a fecha_hasta.")
    dias = (hasta - desde).days + 1
    lunes = desde - dt.timedelta(days=desde.weekday())
    if dias % DIAS_SEMANA:
        raise Error(MENSAJE_SEMANAS)
    with db.transaction(read_only=True) as c:
        inicio = inicio_de_semana(lunes, _feriados(c, _empleado(c, empleado_id)))
    if inicio != desde:
        detalle = f" Esa semana empieza el {_dia(inicio)}." if inicio else ""
        raise Error(MENSAJE_SEMANAS + detalle)
    return [(lunes + dt.timedelta(days=DIAS_SEMANA * i)).isoformat() for i in range(dias // DIAS_SEMANA)]


def validar_rango_semanal(empleado_id, fecha_desde, fecha_hasta):
    semanas_de_rango(empleado_id, fecha_desde, fecha_hasta)


# --- Empleado: calendario de semanas, sus solicitudes y cancelacion --------------------------------------------

def semanas(empleado_id, anio=None):
    """Semanas (lunes) del anio con su estado para el empleado y el saldo en semanas completas."""
    hoy = _hoy()
    anio = int(anio or hoy.year)
    if not 2000 <= anio <= 2100:
        raise Error("Año inválido.")
    with db.transaction(read_only=True) as c:
        empleado = _empleado(c, empleado_id)
        feriados = _feriados(c, empleado)
        tomadas = db.all_rows(c, """SELECT id, COALESCE(solicitud_id, id) AS sid, estado, fecha_desde, fecha_hasta
                                    FROM vacaciones_movimientos
                                    WHERE empleado_id = %s AND tipo = 'tomado' AND estado IN ('pendiente', 'aprobado')
                                      AND revertido_por_movimiento_id IS NULL AND origen_movimiento_id IS NULL
                                      AND fecha_desde <= %s AND fecha_hasta >= %s""",
                              (empleado["id"], dt.date(anio + 1, 1, 7), dt.date(anio - 1, 12, 25)))
    resumen = vs.calcular_resumen_vacaciones(int(empleado["id"]), anio)["vacaciones"]
    disponibles = Decimal(str(resumen["dias_disponibles_con_pendientes"] or 0))
    lunes = dt.date(anio, 1, 1) + dt.timedelta(days=(7 - dt.date(anio, 1, 1).weekday()) % 7)
    salida = []
    while lunes.year == anio:
        inicio = inicio_de_semana(lunes, feriados)
        fin = inicio + dt.timedelta(days=DIAS_SEMANA - 1) if inicio else None
        estado, movimiento = "disponible", None
        if inicio is None:
            estado = "sin_dias_habiles"
        else:
            movimiento = next((m for m in tomadas if vs._parse_date(m["fecha_desde"]) <= fin
                               and vs._parse_date(m["fecha_hasta"]) >= inicio), None)
            if movimiento:
                estado = "aprobada" if movimiento["estado"] == "aprobado" else "pendiente"
            elif inicio <= hoy:
                estado = "pasada"
        salida.append(dict(lunes=lunes.isoformat(), domingo=(lunes + dt.timedelta(days=6)).isoformat(),
                           inicio=inicio.isoformat() if inicio else None, fin=fin.isoformat() if fin else None,
                           feriado_lunes=feriados.get(lunes), estado=estado,
                           solicitud_id=int(movimiento["sid"]) if movimiento else None))
        lunes += dt.timedelta(days=DIAS_SEMANA)
    return dict(
        anio=anio, zona_horaria="America/Argentina/Buenos_Aires", calculado_at=now_local().replace(microsecond=0).isoformat(timespec="seconds") + "-03:00",
        saldo=dict(dias_corresponden=resumen["dias_corresponden"], dias_tomados=resumen["dias_tomados"],
                   dias_pendientes=resumen["dias_pendientes"], dias_disponibles=vs._days_number(disponibles),
                   semanas_disponibles=max(0, int(disponibles // DIAS_SEMANA)),
                   dias_fuera_de_semanas=vs._days_number(disponibles % DIAS_SEMANA) if disponibles > 0 else 0),
        feriados_cargados=any(f.year == anio for f in feriados), reglas=MENSAJE_SEMANAS, semanas=salida,
    )


def mis_solicitudes(empleado_id, anio=None):
    hoy = _hoy()
    donde, args = "vm.empleado_id = %s", [int(empleado_id)]
    if anio:
        donde += " AND vm.anio = %s"
        args.append(int(anio))
    with db.transaction(read_only=True) as c:
        return dict(items=_solicitudes(c, donde, args, hoy, actor_id=int(empleado_id)))


def mi_solicitud(empleado_id, sid):
    with db.transaction(read_only=True) as c:
        solicitud = _solicitud(c, sid, _hoy(), actor_id=int(empleado_id))
    if solicitud["empleado"]["id"] != int(empleado_id):
        raise NoEncontrada("Solicitud no encontrada.")
    return solicitud


def cancelar(empleado_id, sid, motivo=None, *, movimiento_id=None):
    """Lo pendiente se cancela al momento (sin aviso al propio empleado); lo aprobado que todavia no empezo queda
    como pedido de cancelacion para el jefe o RR. HH. Lo que ya empezo no se puede cancelar desde la app."""
    motivo = (str(motivo or "").strip() or "Cancelada por el empleado")[:255]
    solicitud = mi_solicitud(empleado_id, sid)
    tandas = [t for t in solicitud["tandas"] if not movimiento_id or t["movimiento_id"] == int(movimiento_id)]
    if movimiento_id and not tandas:
        raise NoEncontrada("Vacación no encontrada.")
    pendientes = [t for t in tandas if t["estado"] == "pendiente"]
    aprobadas = [t for t in tandas if t["estado"] == "aprobado" and not t["cancelacion_pedida"]]
    if any(t["empezo"] for t in aprobadas):
        raise Error("Esas vacaciones ya empezaron: para cambiarlas hablá con tu jefe o con RR. HH.")
    if not pendientes and not aprobadas:
        raise Error("No hay nada para cancelar en esa solicitud.")
    for t in pendientes:
        vs.rechazar_movimiento_vacaciones(t["movimiento_id"], actor_id=None, motivo=motivo, avisar=False)
    if aprobadas:
        ahora = now_local().replace(microsecond=0)
        with db.transaction() as c:
            ids = [t["movimiento_id"] for t in aprobadas]
            c.execute(f"""UPDATE vacaciones_movimientos SET cancelacion_pedida_at = %s, cancelacion_motivo = %s
                          WHERE id IN ({db_marcas(ids)}) AND estado = 'aprobado' AND revertido_por_movimiento_id IS NULL""",
                      (ahora, motivo, *ids))
        avisos_push.revision_cancelacion_vacaciones(sid)
    _limpiar_si_resuelta(sid)
    return dict(solicitud=mi_solicitud(empleado_id, sid), canceladas=len(pendientes), cancelacion_pedida=len(aprobadas))


# --- Jefe: equipo, calendario, saldos y resolucion ----------------------------------------------------------

def _actor(c, actor_id):
    return _empleado(c, actor_id)


def equipo_solicitudes(actor_id, anio=None, estado=None):
    hoy = _hoy()
    with db.transaction(read_only=True) as c:
        actor = _actor(c, actor_id)
        eq = equipo(c, actor)
        items = []
        if eq["visibles"]:
            ids = sorted(eq["visibles"])
            donde, args = f"vm.empleado_id IN ({db_marcas(ids)})", list(ids)
            if anio:
                donde += " AND vm.anio = %s"
                args.append(int(anio))
            items = _solicitudes(c, donde, args, hoy, directos=eq["directos"])
    if estado == "pendiente":
        items = [s for s in items if s["pendiente"] or s["cancelacion_pedida"]]
    elif estado:
        items = [s for s in items if s["estado"] == estado]
    return dict(alcance=eq["alcance"], es_jefe=bool(eq["directos"]),
                por_resolver=sum(1 for s in items if s["puede_resolver"] or s["puede_resolver_cancelacion"]), items=items)


def equipo_solicitud(actor_id, sid):
    with db.transaction(read_only=True) as c:
        actor = _actor(c, actor_id)
        eq = equipo(c, actor)
        solicitud = _solicitud(c, sid, _hoy(), directos=eq["directos"])
    if solicitud["empleado"]["id"] not in eq["visibles"]:
        raise NoEncontrada("Solicitud no encontrada.")
    return solicitud


def equipo_calendario(actor_id, mes):
    desde = vs._parse_date(f"{mes}-01", "mes") if mes and len(str(mes)) == 7 else None
    if not desde:
        raise Error("'mes' inválido (use AAAA-MM).")
    hasta = (desde.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    hoy = _hoy()
    with db.transaction(read_only=True) as c:
        actor = _actor(c, actor_id)
        eq = equipo(c, actor)
        filas = []
        if eq["visibles"]:
            ids = sorted(eq["visibles"])
            filas = db.all_rows(c, f"""{_SELECT_TANDAS} AND vm.estado IN ('pendiente', 'aprobado')
                                        AND vm.revertido_por_movimiento_id IS NULL
                                        AND vm.empleado_id IN ({db_marcas(ids)}) AND vm.fecha_desde <= %s AND vm.fecha_hasta >= %s
                                        ORDER BY vm.fecha_desde, e.apellido, e.nombre""", (*ids, hasta, desde))
    items = [dict(_tanda(f, hoy), solicitud_id=int(f["sid"]),
                  empleado=dict(id=int(f["empleado_id"]), nombre=_nombre(f), legajo=f.get("legajo"))) for f in filas]
    return dict(mes=desde.strftime("%Y-%m"), desde=desde.isoformat(), hasta=hasta.isoformat(), alcance=eq["alcance"],
                items=items)


def equipo_saldos(actor_id, anio=None):
    anio = int(anio or _hoy().year)
    with db.transaction(read_only=True) as c:
        actor = _actor(c, actor_id)
        eq = equipo(c, actor)
    empleados = [eq["empleados"][i] for i in sorted(eq["visibles"], key=lambda i: _nombre(eq["empleados"][i]))]
    resumenes = vs.calcular_resumenes_vacaciones(empleados, anio, include_errors=True) if empleados else {}
    items = []
    for e in empleados:
        r = resumenes.get(int(e["id"])) or {}
        v = r.get("vacaciones") or {}
        disponibles = Decimal(str(v.get("dias_disponibles_con_pendientes") or 0))
        items.append(dict(empleado=dict(id=int(e["id"]), nombre=_nombre(e), legajo=e.get("legajo")),
                          es_directo=int(e["id"]) in eq["directos"], error=r.get("error"),
                          dias_corresponden=v.get("dias_corresponden"), dias_tomados=v.get("dias_tomados"),
                          dias_pendientes=v.get("dias_pendientes"), dias_disponibles=vs._days_number(disponibles) if v else None,
                          semanas_disponibles=max(0, int(disponibles // DIAS_SEMANA)) if v else None))
    return dict(anio=anio, alcance=eq["alcance"], items=items)


def _para_resolver(actor_id, sid):
    """La solicitud, si el actor es el jefe directo de quien la pidio."""
    with db.transaction(read_only=True) as c:
        actor = _actor(c, actor_id)
        eq = equipo(c, actor)
        solicitud = _solicitud(c, sid, _hoy(), directos=eq["directos"])
    if solicitud["empleado"]["id"] not in eq["visibles"]:
        raise NoEncontrada("Solicitud no encontrada.")
    if solicitud["empleado"]["id"] not in eq["directos"]:
        raise SinPermiso("Solo su jefe directo (o RR. HH. desde el panel) puede resolver esta solicitud.")
    return actor, solicitud


def _marcar_resolvio(ids, actor_id):
    if ids:
        with db.transaction() as c:
            c.execute(f"UPDATE vacaciones_movimientos SET resuelto_por_empleado_id = %s WHERE id IN ({db_marcas(ids)})",
                      (int(actor_id), *ids))


def aprobar(actor_id, sid):
    actor, solicitud = _para_resolver(actor_id, sid)
    ids = [t["movimiento_id"] for t in solicitud["tandas"] if t["estado"] == "pendiente"]
    if not ids:
        raise Error("La solicitud ya fue resuelta.")
    aprobadas = []
    try:
        for mid in ids:
            vs.aprobar_movimiento_vacaciones(mid, actor_id=None, avisar=False)
            aprobadas.append(mid)
    finally:
        _marcar_resolvio(aprobadas, actor_id)
        if aprobadas:
            avisos_push.vacaciones_solicitud_resuelta(sid, "aprobada", aprobadas, actor=_nombre(actor))
            _limpiar_si_resuelta(sid)
    return equipo_solicitud(actor_id, sid)


def rechazar(actor_id, sid, motivo):
    motivo = str(motivo or "").strip()
    if not motivo:
        raise Error("Indicá el motivo del rechazo.")
    actor, solicitud = _para_resolver(actor_id, sid)
    ids = [t["movimiento_id"] for t in solicitud["tandas"] if t["estado"] == "pendiente"]
    if not ids:
        raise Error("La solicitud ya fue resuelta.")
    for mid in ids:
        vs.rechazar_movimiento_vacaciones(mid, actor_id=None, motivo=motivo[:255], avisar=False)
    _marcar_resolvio(ids, actor_id)
    avisos_push.vacaciones_solicitud_resuelta(sid, "rechazada", ids, actor=_nombre(actor), motivo=motivo)
    _limpiar_si_resuelta(sid)
    return equipo_solicitud(actor_id, sid)


def resolver_cancelacion(actor_id, sid, aprobar_cancelacion, motivo=None):
    actor, solicitud = _para_resolver(actor_id, sid)
    tandas = [t for t in solicitud["tandas"] if t["cancelacion_pedida"]]
    if not tandas:
        raise Error("No hay un pedido de cancelación para resolver.")
    ids = [t["movimiento_id"] for t in tandas]
    if aprobar_cancelacion:
        for t in tandas:
            vs.cancelar_movimiento_vacaciones(t["movimiento_id"], actor_id=None,
                                              motivo=t["cancelacion_motivo"] or "Cancelación pedida por el empleado",
                                              avisar=False)
        _marcar_resolvio(ids, actor_id)
        avisos_push.vacaciones_solicitud_resuelta(sid, "cancelada", ids, actor=_nombre(actor))
    else:
        motivo = str(motivo or "").strip()
        if not motivo:
            raise Error("Indicá el motivo para mantener las vacaciones.")
        with db.transaction() as c:
            c.execute(f"""UPDATE vacaciones_movimientos SET cancelacion_pedida_at = NULL, cancelacion_motivo = NULL
                          WHERE id IN ({db_marcas(ids)})""", tuple(ids))
        avisos_push.vacaciones_solicitud_resuelta(sid, "cancelacion_rechazada", ids, actor=_nombre(actor), motivo=motivo)
    _limpiar_si_resuelta(sid)
    return equipo_solicitud(actor_id, sid)


def _limpiar_si_resuelta(sid):
    """Si no queda nada por resolver: fuera los push "para revisar" sin enviar y leidas las notificaciones de los
    revisores (ya no hay nada que hacer)."""
    try:
        with db.transaction(read_only=True) as c:
            pendiente = db.one(c, """SELECT 1 AS x FROM vacaciones_movimientos
                                     WHERE COALESCE(solicitud_id, id) = %s AND tipo = 'tomado' AND origen_movimiento_id IS NULL
                                       AND (estado = 'pendiente' OR (estado = 'aprobado' AND cancelacion_pedida_at IS NOT NULL
                                            AND revertido_por_movimiento_id IS NULL)) LIMIT 1""", (int(sid),))
        if not pendiente:
            avisos_push.limpiar_revision_vacaciones(sid)
    except Exception:
        logger.warning("vacaciones_limpieza_error", exc_info=True, extra={"extra": {"solicitud_id": sid}})


def al_resolver_movimiento(movimiento_id):
    """Desde el panel (un movimiento por vez): limpia los avisos de revision si la solicitud quedo resuelta."""
    with db.transaction(read_only=True) as c:
        fila = db.one(c, "SELECT COALESCE(solicitud_id, id) AS sid FROM vacaciones_movimientos WHERE id = %s",
                      (int(movimiento_id),))
    if fila:
        _limpiar_si_resuelta(fila["sid"])


def anios_sin_feriados(empresa_id, hoy=None):
    """Anios (el actual y, desde octubre, el siguiente) sin ningun dia no laborable cargado para la empresa: sin ese
    calendario no se sabe si un lunes es feriado. Para el aviso del panel."""
    hoy = hoy or _hoy()
    anios = [hoy.year] + ([hoy.year + 1] if hoy.month >= 10 else [])
    with db.transaction(read_only=True) as c:
        cargados = {int(f["anio"]) for f in db.all_rows(
            c, f"""SELECT DISTINCT YEAR(fecha) AS anio FROM asistencia_dias_no_laborables
                   WHERE (empresa_id = 0 OR empresa_id = %s) AND sector_id = 0 AND YEAR(fecha) IN ({db_marcas(anios)})""",
            (int(empresa_id or 0), *anios))}
    return [a for a in anios if a not in cargados]
