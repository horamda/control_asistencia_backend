"""Reglas de avisos push por empresa: si estan activos, a quien van, cuando salen y sus tiempos.

Cada aviso del sistema pertenece a una regla del CATALOGO. La empresa solo guarda lo que cambia (push_reglas);
lo demas usa los valores por defecto. Ademas hay un horario de silencio por empresa (push_config): lo que cae
adentro sale cuando termina, salvo los avisos urgentes, que se descartan porque ya perdieron sentido.

Momento de envio:
- inmediato: sale en el proximo minuto (o al terminar el silencio).
- resumen: se junta y sale a los horarios elegidos (p. ej. 08:00 y 13:00, de lunes a viernes) en un solo aviso
  por persona. Solo para las solicitudes que se revisan (RR. HH., jefes, Seguridad e Higiene).
"""
import datetime as dt
import threading
import time

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

EMPLEADO, JEFE, RRHH, SEGURIDAD = "empleado", "jefe_directo", "rrhh", "responsable_sh"
JEFE_SUPERIOR = "jefe_superior"
DESTINATARIOS = {
    EMPLEADO: "El empleado",
    JEFE: "Jefe directo",
    JEFE_SUPERIOR: "Jefe del jefe directo",
    RRHH: "RR. HH. (quien puede aprobar)",
    SEGURIDAD: "Responsable de Seguridad e Higiene",
}
DIAS = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}
GRUPOS = {
    "empleado": "Avisos al empleado",
    "revision": "Solicitudes para revisar",
    "seguridad": "Seguridad e Higiene",
}


def _r(clave, grupo, nombre, descripcion, *, destinatarios=(EMPLEADO,), posibles=None, resumen=False,
       urgente=False, parametro=None):
    return dict(clave=clave, grupo=grupo, nombre=nombre, descripcion=descripcion,
                destinatarios=list(destinatarios), posibles=list(posibles or destinatarios),
                resumen=resumen, urgente=urgente, parametro=parametro)


def _revision(modulo, nombre, descripcion, destinatarios=(JEFE, RRHH), posibles=(JEFE, RRHH)):
    return _r(f"revision:{modulo}", "revision", nombre, descripcion, destinatarios=destinatarios,
              posibles=posibles, resumen=True)


CATALOGO = [
    _r("reuniones", "empleado", "Cambios en reuniones", "Reunión nueva, cambio de horario o lugar, fecha cancelada o reactivada."),
    _r("recordatorio_reunion", "empleado", "Recordatorio de reunión", "Antes de empezar, a quien todavía no registró la asistencia.",
       urgente=True, parametro=dict(etiqueta="Minutos antes", default=30, min=5, max=240)),
    _r("salida_pendiente", "empleado", "Salida sin fichar", "La jornada sigue abierta después de la salida prevista.",
       urgente=True, parametro=dict(etiqueta="Minutos después de la salida", default=30, min=10, max=240)),
    _r("ingreso_pendiente", "empleado", "Ingreso sin fichar",
       "Tiene horario hoy y no fichó el ingreso pasada la hora prevista. No avisa con licencia, justificación aprobada, "
       "vacaciones, franco, feriado ni después de terminado el horario.",
       destinatarios=(EMPLEADO, JEFE), posibles=(EMPLEADO, JEFE), urgente=True,
       parametro=dict(etiqueta="Minutos después del ingreso", default=15, min=5, max=240)),
    _r("justificacion", "empleado", "Justificación resuelta", "Aprobada o rechazada, con el motivo."),
    _r("vacaciones", "empleado", "Vacaciones resueltas",
       "Aprobadas, rechazadas, canceladas o cargadas por RR. HH.; también compensatorios y ajustes."),
    _r("vacaciones_inicio", "empleado", "Inicio de vacaciones",
       "El día hábil anterior al inicio: al empleado y, si se elige, a su jefe directo.",
       destinatarios=(EMPLEADO,), posibles=(EMPLEADO, JEFE)),
    _r("adelanto", "empleado", "Adelanto resuelto", "Aprobado o rechazado."),
    _r("pedido_mercaderia", "empleado", "Pedido de mercadería resuelto", "Aprobado o rechazado."),
    _r("reintegro", "empleado", "Viáticos", "Rendición aprobada, rechazada, devuelta para corregir o pagada."),
    _r("reintegro_recordatorio", "empleado", "Recordatorio de viáticos", "El día 5, completar los viáticos del mes anterior."),
    _r("epp", "empleado", "EPP", "Pedido aprobado, rechazado o entregado."),
    _r("feedback", "empleado", "Feedback", "Al responsable cuando le asignan uno y al empleado cuando se resuelve."),
    _r("trivia", "empleado", "Trivias", "Trivia nueva y recordatorios antes del cierre, a quien todavía no jugó."),
    _revision("justificaciones", "Justificación enviada", "Un empleado envió una justificación."),
    _revision("vacaciones", "Vacaciones pedidas", "Un empleado pidió vacaciones o pidió cancelar unas aprobadas."),
    _r("vacaciones_escalar", "revision", "Vacaciones sin resolver",
       "Una solicitud sigue pendiente pocos días antes de empezar: aviso, una sola vez.",
       destinatarios=(JEFE_SUPERIOR, RRHH), posibles=(JEFE_SUPERIOR, RRHH), resumen=True,
       parametro=dict(etiqueta="Días antes del inicio", default=3, min=1, max=30)),
    _revision("pedidos_empleados", "Adelanto o pedido de mercadería", "Un empleado pidió un adelanto o cargó un pedido de mercadería."),
    _revision("reintegros", "Viáticos enviados", "Un empleado envió (o reenvió corregida) una rendición de viáticos."),
    _revision("epp", "Pedido de EPP", "Un empleado envió un pedido de EPP."),
    _r("revision:seguridad_higiene", "seguridad", "Reporte nuevo", "Un empleado cargó un reporte (acto o condición insegura, incidente, accidente).",
       destinatarios=(SEGURIDAD,), posibles=(SEGURIDAD, JEFE), resumen=True),
    _r("seguridad_resultado", "seguridad", "Resultado del reporte", "A quien reportó: su reporte fue aprobado o rechazado."),
    _r("seguridad_accion", "seguridad", "Acción correctiva", "Al responsable: acción asignada, por vencer y vencida.",
       parametro=dict(etiqueta="Días antes del vencimiento", default=1, min=0, max=30)),
]
POR_CLAVE = {r["clave"]: r for r in CATALOGO}

# Regla de cada tipo de push. Los que no estan (comunicado, prueba) no tienen regla: salen siempre y al momento.
TIPO_REGLA = {
    "reunion_nueva": "reuniones", "reunion_cambio": "reuniones", "reunion_cancelada": "reuniones",
    "reunion_reactivada": "reuniones", "reunion_horario": "reuniones", "recordatorio": "recordatorio_reunion",
    "salida_pendiente": "salida_pendiente", "justificacion": "justificacion", "vacaciones": "vacaciones",
    "ingreso_pendiente": "ingreso_pendiente", "ingreso_equipo": "ingreso_pendiente",
    "adelanto": "adelanto", "pedido_mercaderia": "pedido_mercaderia", "reintegro": "reintegro",
    "vacaciones_inicio": "vacaciones_inicio", "vacaciones_equipo": "vacaciones_inicio",
    "reintegro_recordatorio": "reintegro_recordatorio", "epp_resuelto": "epp", "epp_entregado": "epp",
    "feedback_asignado": "feedback", "feedback_resuelto": "feedback", "trivia_nueva": "trivia",
    "trivia_recordatorio": "trivia", "seguridad_resultado": "seguridad_resultado",
    "seguridad_accion": "seguridad_accion",
}

_CACHE_SEGUNDOS = 60
_cache = {}
_lock = threading.Lock()


def _hora(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, dt.timedelta):  # mysql-connector devuelve TIME como timedelta
        segundos = int(valor.total_seconds()) % 86400
        return dt.time(segundos // 3600, segundos % 3600 // 60)
    if isinstance(valor, dt.time):
        return valor.replace(second=0, microsecond=0)
    try:
        horas, minutos = str(valor).strip()[:5].split(":")
        return dt.time(int(horas), int(minutos))
    except ValueError:
        raise Error(f"Hora inválida: {valor}.") from None


def _lista(texto):
    return [p.strip() for p in str(texto or "").split(",") if p.strip()]


def _defecto(meta):
    return dict(clave=meta["clave"], activo=True, destinatarios=list(meta["destinatarios"]), momento="inmediato",
                horarios=[], dias=[], parametro=meta["parametro"]["default"] if meta["parametro"] else None)


def _combinar(meta, fila):
    regla = _defecto(meta)
    if not fila:
        return regla
    regla["activo"] = bool(fila["activo"])
    destinatarios = [d for d in _lista(fila.get("destinatarios")) if d in meta["posibles"]]
    if fila.get("destinatarios") is not None:
        regla["destinatarios"] = destinatarios
    if meta["resumen"] and fila.get("momento") == "resumen":
        regla["momento"] = "resumen"
        regla["horarios"] = sorted({_hora(h) for h in _lista(fila.get("horarios"))} - {None})
        regla["dias"] = sorted({int(d) for d in _lista(fila.get("dias")) if d.isdigit() and 1 <= int(d) <= 7})
    if meta["parametro"] and fila.get("parametro") is not None:
        regla["parametro"] = int(fila["parametro"])
    return regla


def _leer(empresa_id):
    try:
        with db.transaction(read_only=True) as c:
            filas = {f["clave"]: f for f in db.all_rows(c, "SELECT * FROM push_reglas WHERE empresa_id=%s", (empresa_id,))}
            config = db.one(c, "SELECT silencio_desde, silencio_hasta FROM push_config WHERE empresa_id=%s", (empresa_id,))
    except Exception:  # sin la migracion (o sin base) rigen los valores por defecto
        filas, config = {}, None
    reglas = {meta["clave"]: _combinar(meta, filas.get(meta["clave"])) for meta in CATALOGO}
    silencio = (_hora(config["silencio_desde"]), _hora(config["silencio_hasta"])) if config else (None, None)
    return reglas, silencio


def configuracion(empresa_id):
    """(reglas por clave, (silencio_desde, silencio_hasta)), cacheado un minuto por proceso."""
    ahora = time.monotonic()
    with _lock:
        guardado = _cache.get(int(empresa_id))
        if guardado and guardado[0] > ahora:
            return guardado[1]
    valor = _leer(int(empresa_id))
    with _lock:
        _cache[int(empresa_id)] = (ahora + _CACHE_SEGUNDOS, valor)
    return valor


def invalidar(empresa_id=None):
    with _lock:
        if empresa_id is None:
            _cache.clear()
        else:
            _cache.pop(int(empresa_id), None)


def regla(empresa_id, clave):
    return configuracion(empresa_id)[0].get(clave) or (_defecto(POR_CLAVE[clave]) if clave in POR_CLAVE else None)


def parametro(empresa_id, clave):
    valor = (regla(empresa_id, clave) or {}).get("parametro")
    return valor if valor is not None else POR_CLAVE[clave]["parametro"]["default"]


# --- Cuando sale un aviso ------------------------------------------------------------------------------

def en_silencio(momento, desde, hasta):
    if not desde or not hasta or desde == hasta:
        return False
    hora = momento.time()
    return desde <= hora < hasta if desde < hasta else (hora >= desde or hora < hasta)


def fin_silencio(momento, hasta):
    candidato = dt.datetime.combine(momento.date(), hasta)
    return candidato if candidato > momento else candidato + dt.timedelta(days=1)


def proximo_horario(momento, horarios, dias):
    """Primer horario (de los dias elegidos; sin dias = todos) estrictamente posterior a `momento`."""
    for adelante in range(0, 8):
        fecha = momento.date() + dt.timedelta(days=adelante)
        if dias and fecha.isoweekday() not in dias:
            continue
        for hora in horarios:
            candidato = dt.datetime.combine(fecha, hora)
            if candidato > momento:
                return candidato
    return None


def planificar(empresa_id, clave, momento=None):
    """(enviar, programado_para, lote) para un aviso de la regla `clave` generado ahora."""
    meta = POR_CLAVE.get(clave)
    if not meta:
        return True, None, None
    momento = momento or now_local()
    reglas, (desde, hasta) = configuracion(empresa_id)
    actual = reglas.get(clave) or _defecto(meta)
    if not actual["activo"]:
        return False, None, None
    if actual["momento"] == "resumen" and actual["horarios"]:
        horario = proximo_horario(momento, actual["horarios"], actual["dias"])
        if horario:
            return True, horario, f"{clave}:{horario:%Y%m%d%H%M}"
    if en_silencio(momento, desde, hasta):
        if meta["urgente"]:
            return False, None, None
        return True, fin_silencio(momento, hasta), None
    return True, None, None


# --- Panel -------------------------------------------------------------------------------------------

def vista(who):
    reglas, (desde, hasta) = _leer(who["empresa_id"])  # sin cache: el panel muestra lo guardado
    grupos = []
    for grupo, titulo in GRUPOS.items():
        items = [dict(meta, actual=reglas[meta["clave"]]) for meta in CATALOGO if meta["grupo"] == grupo]
        grupos.append(dict(clave=grupo, titulo=titulo, reglas=items))
    return dict(grupos=grupos, silencio_desde=desde, silencio_hasta=hasta, destinatarios=DESTINATARIOS, dias=DIAS)


def guardar(who, form):
    """form: MultiDict del panel (activo:<clave>, destinatario:<clave>, momento:<clave>, horarios:<clave>,
    dias:<clave>, parametro:<clave>, silencio_desde, silencio_hasta)."""
    ahora = now_local().replace(microsecond=0)
    filas = []
    for meta in CATALOGO:
        clave = meta["clave"]
        destinatarios = [d for d in form.getlist(f"destinatario:{clave}") if d in meta["posibles"]]
        if len(meta["posibles"]) == 1:
            destinatarios = list(meta["posibles"])
        momento, horarios, dias = "inmediato", "", ""
        if meta["resumen"] and form.get(f"momento:{clave}") == "resumen":
            lista = sorted({_hora(h) for h in _lista(form.get(f"horarios:{clave}", "").replace(" ", ","))} - {None})
            if not lista:
                raise Error(f"«{meta['nombre']}»: indicá al menos un horario para el resumen (p. ej. 08:00, 13:00).")
            momento, horarios = "resumen", ",".join(h.strftime("%H:%M") for h in lista)
            dias = ",".join(d for d in form.getlist(f"dias:{clave}") if d.isdigit() and 1 <= int(d) <= 7)
        parametro = None
        if meta["parametro"]:
            limite = meta["parametro"]
            try:
                parametro = int(form.get(f"parametro:{clave}") or limite["default"])
            except ValueError:
                raise Error(f"«{meta['nombre']}»: {limite['etiqueta'].lower()} debe ser un número.") from None
            if not limite["min"] <= parametro <= limite["max"]:
                raise Error(f"«{meta['nombre']}»: {limite['etiqueta'].lower()} entre {limite['min']} y {limite['max']}.")
        activo = 1 if form.get(f"activo:{clave}") else 0
        if activo and not destinatarios:
            raise Error(f"«{meta['nombre']}»: elegí a quién avisar o desactivalo.")
        filas.append((who["empresa_id"], clave, activo, ",".join(destinatarios), momento, horarios or None,
                      dias or None, parametro, ahora, who.get("user_id")))
    desde, hasta = _hora(form.get("silencio_desde")), _hora(form.get("silencio_hasta"))
    if bool(desde) != bool(hasta):
        raise Error("Para el horario de silencio indicá desde y hasta (o dejá los dos vacíos).")
    with db.transaction() as c:
        c.executemany("""INSERT INTO push_reglas (empresa_id, clave, activo, destinatarios, momento, horarios, dias,
                                                  parametro, actualizado_at, actualizado_por)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                         ON DUPLICATE KEY UPDATE activo=VALUES(activo), destinatarios=VALUES(destinatarios),
                           momento=VALUES(momento), horarios=VALUES(horarios), dias=VALUES(dias),
                           parametro=VALUES(parametro), actualizado_at=VALUES(actualizado_at),
                           actualizado_por=VALUES(actualizado_por)""", filas)
        c.execute("""INSERT INTO push_config (empresa_id, silencio_desde, silencio_hasta, actualizado_at, actualizado_por)
                     VALUES (%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE silencio_desde=VALUES(silencio_desde), silencio_hasta=VALUES(silencio_hasta),
                       actualizado_at=VALUES(actualizado_at), actualizado_por=VALUES(actualizado_por)""",
                  (who["empresa_id"], desde, hasta, ahora, who.get("user_id")))
    invalidar(who["empresa_id"])
    return len(filas)
