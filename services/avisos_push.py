"""Avisos push al empleado fuera de Reuniones (solo con Firebase configurado; nunca rompen la accion).

- Salida pendiente: la jornada de hoy sigue abierta 30 min despues de la salida prevista (scheduler cada 5 min).
- Resoluciones: EPP (aprobado, aprobado con menos, rechazado, entregado), viaticos y reintegros (aprobada,
  rechazada, devuelta, pagada), adelantos y pedidos de mercaderia (aprobado, rechazado).
- Recordatorio mensual de viaticos (dia 5) por push ademas del aviso dentro de la app.
- Justificaciones y vacaciones (aprobadas o rechazadas), feedback (al responsable cuando se lo asignan y al
  empleado cuando se resuelve) y trivias (nueva y recordatorios de 24 h y 2 h antes del cierre).
- Solicitudes para revisar (justificacion, vacaciones, adelanto, mercaderia, viaticos, EPP, reporte de
  seguridad): al jefe directo, a RR. HH. (usuarios del panel vinculados a un empleado que pueden aprobar el
  modulo) y/o al responsable de Seguridad e Higiene, segun la regla de la empresa.
- Seguridad e Higiene: resultado de la revision a quien reporto y acciones correctivas al responsable
  (asignada, por vencer y vencida).

Cada regla (push_reglas_service) decide si el aviso esta activo, a quien va y cuando sale.

Cada aviso lleva data.tipo, data.ruta (pantalla a abrir) y el id del registro."""

import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal

from repositories import carga_repository as db
from services import push_reglas_service as reglas_push
from services import push_service
from services.carga_service import now_local

logger = logging.getLogger(__name__)
MARGEN_SALIDA_MIN = 30
# Salida prevista por jornada (minutos del dia): se calcula una vez por asistencia y se descarta al cambiar el dia.
_previstas = {"fecha": None, "fin": {}}


def _hhmm(minutos):
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _pesos(valor):
    return "$ " + f"{float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _avisar(empresa_id, empleado_id, tipo, titulo, cuerpo, datos, clave, bandeja=None):
    extra = {} if bandeja is None else {"bandeja": bandeja}  # None: lo decide el tipo (notificaciones_service)
    return push_service.encolar_ahora(empresa_id, [empleado_id], tipo, titulo, cuerpo, datos, clave, **extra)


def _seguro(funcion):
    """Un aviso que falla (consulta, tabla) se registra y no interrumpe la accion del panel o la app.
    Corre aunque Firebase no este configurado: la novedad queda en la bandeja (notificaciones_service)."""
    def envoltura(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except Exception:
            logger.warning("aviso_push_error", exc_info=True, extra={"extra": {"aviso": funcion.__name__}})
            return 0
    envoltura.__name__ = funcion.__name__
    envoltura.__doc__ = funcion.__doc__
    return envoltura


# --- Salida pendiente ----------------------------------------------------------------------------

@_seguro
def salidas_pendientes(ahora=None):
    """Avisa una vez por jornada a quien sigue sin fichar la salida 30 min despues de la prevista
    (fin del bloque de su horario o ingreso + horas de la empresa, la misma que usaria el egreso automatico)."""
    from services import egreso_automatico_service as egreso  # importa el calculo de horarios solo aca

    if not push_service.activo():  # solo push (sin bandeja): sin Firebase no hay nada que calcular
        return 0
    ahora = ahora or now_local()
    hoy = ahora.date()
    if _previstas["fecha"] != hoy:
        _previstas.update(fecha=hoy, fin={})
    with db.transaction(read_only=True) as c:
        abiertas = db.all_rows(
            c,
            """SELECT a.id, a.empresa_id, a.empleado_id, a.hora_entrada,
                      COALESCE(ce.egreso_automatico_activo, 1) AS automatico,
                      COALESCE(ce.egreso_automatico_horas, %s) AS horas
               FROM asistencias a
               LEFT JOIN configuracion_empresa ce ON ce.empresa_id = a.empresa_id
               WHERE a.fecha = %s AND a.hora_entrada IS NOT NULL AND a.hora_salida IS NULL
                 AND EXISTS (SELECT 1 FROM push_dispositivos d WHERE d.empleado_id = a.empleado_id AND d.activo = 1)
                 AND NOT EXISTS (SELECT 1 FROM push_envios p
                                 WHERE p.clave = CONCAT('salida:', a.id, ':', a.empleado_id))""",
            (egreso.HORAS_DEFAULT, hoy))
    minuto = ahora.hour * 60 + ahora.minute
    avisados = 0
    for row in abiertas:
        fin = _previstas["fin"].get(row["id"])
        if fin is None:
            hora, _ = egreso.calcular_egreso(row["hora_entrada"], egreso._bloques(row["empleado_id"], hoy),
                                             float(row["horas"]))
            fin = _previstas["fin"][row["id"]] = egreso._minutes(hora)
        margen = reglas_push.parametro(row["empresa_id"], "salida_pendiente")
        if fin >= egreso.FIN_DEL_DIA or minuto < fin + margen:
            continue
        entrada = _hhmm(egreso._minutes(row["hora_entrada"]))
        cuerpo = f"Entraste a las {entrada} y tu salida prevista era a las {_hhmm(fin)}. Registrala en la app."
        if row["automatico"]:
            cuerpo += f" Si no, esta noche se cierra sola a las {_hhmm(fin)} y cuenta como olvido de fichada."
        avisados += _avisar(row["empresa_id"], row["empleado_id"], "salida_pendiente",
                            "¿Te olvidaste de fichar la salida?", cuerpo,
                            {"asistencia_id": row["id"], "fecha": hoy.isoformat(), "ruta": "/asistencia"},
                            f"salida:{row['id']}")
    return avisados


# --- EPP -----------------------------------------------------------------------------------------

@_seguro
def epp_resuelto(pedido_id):
    with db.transaction(read_only=True) as c:
        p = db.one(c, """SELECT p.id, p.empresa_id, p.empleado_id, p.estado, p.revision,
                                SUM(l.cantidad) AS pedida, SUM(COALESCE(l.aprobada, 0)) AS aprobada,
                                MAX(NULLIF(l.motivo, '')) AS motivo
                         FROM epp_pedidos p JOIN epp_lineas l ON l.pedido_id = p.id
                         WHERE p.id = %s GROUP BY p.id""", (pedido_id,))
    if not p or p["estado"] not in ("aprobado", "rechazado"):
        return 0
    motivo = f" Motivo: {p['motivo']}" if p["motivo"] else ""
    if p["estado"] == "rechazado":
        titulo, cuerpo = "Pedido de EPP rechazado", f"Tu pedido N° {p['id']} fue rechazado.{motivo}"
    elif int(p["aprobada"]) < int(p["pedida"]):
        titulo = "Pedido de EPP aprobado con cambios"
        cuerpo = f"De tu pedido N° {p['id']} se aprobaron {int(p['aprobada'])} de {int(p['pedida'])} unidades.{motivo}"
    else:
        titulo, cuerpo = "Pedido de EPP aprobado", f"Tu pedido N° {p['id']} fue aprobado. Te avisamos cuando esté para retirar."
    return _avisar(p["empresa_id"], p["empleado_id"], "epp_resuelto", titulo, cuerpo,
                   {"pedido_id": p["id"], "estado": p["estado"], "ruta": f"/epp/{p['id']}"},
                   f"epp:{p['id']}:r{p['revision']}")


@_seguro
def epp_entregado(pedido_id, entrega_id):
    with db.transaction(read_only=True) as c:
        p = db.one(c, "SELECT id, empresa_id, empleado_id, estado FROM epp_pedidos WHERE id = %s", (pedido_id,))
    if not p:
        return 0
    if p["estado"] == "parcial":
        titulo, cuerpo = "Entrega parcial de EPP", f"Se registró una entrega parcial de tu pedido N° {p['id']}. El resto queda pendiente."
    else:
        titulo, cuerpo = "Pedido de EPP entregado", f"Se registró la entrega completa de tu pedido N° {p['id']}."
    return _avisar(p["empresa_id"], p["empleado_id"], "epp_entregado", titulo, cuerpo,
                   {"pedido_id": p["id"], "estado": p["estado"], "ruta": f"/epp/{p['id']}"},
                   f"epp-entrega:{entrega_id}")


# --- Viaticos y reintegros ---------------------------------------------------------------------------

_REINTEGRO = {
    "aprobada": ("Viáticos aprobados", "Tu rendición N° {id} fue aprobada por {total}."),
    "rechazada": ("Viáticos rechazados", "Tu rendición N° {id} fue rechazada.{motivo}"),
    "devuelta": ("Viáticos para corregir", "Te devolvieron la rendición N° {id} para corregir.{motivo}"),
    "pagada": ("Viáticos pagados", "Se registró el pago de tu rendición N° {id} por {total}."),
}


@_seguro
def reintegro_actualizado(solicitud_id):
    with db.transaction(read_only=True) as c:
        r = db.one(c, """SELECT id, empresa_id, empleado_id, estado, revision, total_aprobado, motivo
                         FROM reintegro_solicitudes WHERE id = %s""", (solicitud_id,))
    if not r or r["estado"] not in _REINTEGRO:
        return 0
    titulo, plantilla = _REINTEGRO[r["estado"]]
    motivo = f" Motivo: {r['motivo']}" if r.get("motivo") else ""
    cuerpo = plantilla.format(id=r["id"], total=_pesos(r["total_aprobado"]), motivo=motivo)
    return _avisar(r["empresa_id"], r["empleado_id"], "reintegro", titulo, cuerpo,
                   {"solicitud_id": r["id"], "estado": r["estado"], "ruta": f"/reintegros/{r['id']}"},
                   f"reintegro:{r['id']}:r{r['revision']}")


@_seguro
def recordatorio_viaticos(periodo, mensaje):
    """Dia 5: el mismo recordatorio que ve la app, por push, a quien todavia no lo leyo. Solo push."""
    if not push_service.activo():
        return 0
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, """SELECT empresa_id, empleado_id FROM reintegro_recordatorios
                                  WHERE periodo = %s AND leido_at IS NULL""", (periodo,))
    total = 0
    for fila in filas:
        total += _avisar(fila["empresa_id"], fila["empleado_id"], "reintegro_recordatorio", "Viáticos del mes",
                         mensaje, {"periodo": periodo.isoformat(), "ruta": "/reintegros"}, f"viaticos-mes:{periodo:%Y%m}")
    return total


# --- Adelantos y pedidos de mercaderia --------------------------------------------------------------

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")


@_seguro
def adelanto_resuelto(adelanto_id):
    with db.transaction(read_only=True) as c:
        a = db.one(c, "SELECT id, empresa_id, empleado_id, estado, periodo_month FROM adelantos WHERE id = %s",
                   (adelanto_id,))
    if not a or a["estado"] not in ("aprobado", "rechazado"):
        return 0
    mes = _MESES[int(a["periodo_month"]) - 1]
    return _avisar(a["empresa_id"], a["empleado_id"], "adelanto",
                   f"Adelanto {a['estado']}", f"Tu pedido de adelanto de {mes} fue {a['estado']}.",
                   {"adelanto_id": a["id"], "estado": a["estado"], "ruta": "/adelantos"},
                   f"adelanto:{a['id']}:{a['estado']}")


@_seguro
def pedido_mercaderia_resuelto(pedido_id):
    with db.transaction(read_only=True) as c:
        p = db.one(c, """SELECT id, empresa_id, empleado_id, estado, periodo_month, motivo_rechazo
                         FROM pedidos_mercaderia WHERE id = %s""", (pedido_id,))
    if not p or p["estado"] not in ("aprobado", "rechazado"):
        return 0
    mes = _MESES[int(p["periodo_month"]) - 1]
    cuerpo = f"Tu pedido de mercadería de {mes} fue {p['estado']}."
    if p["estado"] == "rechazado" and p.get("motivo_rechazo"):
        cuerpo += f" Motivo: {p['motivo_rechazo']}"
    return _avisar(p["empresa_id"], p["empleado_id"], "pedido_mercaderia", f"Pedido de mercadería {p['estado']}",
                   cuerpo, {"pedido_id": p["id"], "estado": p["estado"], "ruta": "/pedidos-mercaderia"},
                   f"mercaderia:{p['id']}:{p['estado']}")


# --- Justificaciones y vacaciones -------------------------------------------------------------------

def _dia(valor):
    if isinstance(valor, str):
        valor = dt.date.fromisoformat(valor[:10])
    return valor.strftime("%d/%m")


def _rango(desde, hasta):
    if not desde:
        return ""
    inicio, fin = _dia(desde), _dia(hasta or desde)
    return f" del {inicio}" if inicio == fin else f" del {inicio} al {fin}"


@_seguro
def justificacion_resuelta(justificacion_id):
    with db.transaction(read_only=True) as c:
        j = db.one(c, """SELECT j.id, j.empleado_id, e.empresa_id, j.estado, j.fecha, j.fecha_desde, j.fecha_hasta,
                                j.motivo_rechazo
                         FROM justificaciones j JOIN empleados e ON e.id = j.empleado_id
                         WHERE j.id = %s""", (justificacion_id,))
    if not j or j["estado"] not in ("aprobada", "rechazada"):
        return 0
    cuerpo = f"Tu justificación{_rango(j['fecha_desde'] or j['fecha'], j['fecha_hasta'] or j['fecha'])} fue {j['estado']}."
    if j["estado"] == "rechazada" and j.get("motivo_rechazo"):
        cuerpo += f" Motivo: {j['motivo_rechazo']}"
    return _avisar(j["empresa_id"], j["empleado_id"], "justificacion", f"Justificación {j['estado']}", cuerpo,
                   {"justificacion_id": j["id"], "estado": j["estado"], "ruta": "/justificaciones"},
                   f"justificacion:{j['id']}:{j['estado']}")


def _dias(valor):
    valor = Decimal(str(valor or 0))
    texto = str(int(valor)) if valor == valor.to_integral_value() else str(valor).rstrip("0").replace(".", ",")
    return f"{texto} día" + ("" if valor == 1 else "s")


@_seguro
def vacaciones_resueltas(movimiento_id):
    with db.transaction(read_only=True) as c:
        v = db.one(c, """SELECT id, COALESCE(solicitud_id, id) AS sid, empresa_id, empleado_id, tipo, estado, dias,
                                fecha_desde, fecha_hasta, motivo_resolucion
                         FROM vacaciones_movimientos WHERE id = %s""", (movimiento_id,))
    if not v or v["estado"] not in ("aprobado", "rechazado"):
        return 0
    if v["tipo"] == "tomado":  # desde el panel: un aviso por tanda resuelta, con el formato de la solicitud
        evento = "aprobada" if v["estado"] == "aprobado" else "rechazada"
        return vacaciones_solicitud_resuelta(v["sid"], evento, [v["id"]], motivo=v.get("motivo_resolucion"))
    detalle = f"{_rango(v['fecha_desde'], v['fecha_hasta'])} ({_dias(abs(Decimal(str(v['dias'] or 0))))})"
    if v["tipo"] == "tomado":
        estado = "aprobadas" if v["estado"] == "aprobado" else "rechazadas"
        titulo, cuerpo = f"Vacaciones {estado}", f"Tus vacaciones{detalle} fueron {estado}."
    else:
        nombre = "días compensatorios" if v["tipo"] == "compensatorio" else "ajuste de vacaciones"
        titulo, cuerpo = f"Pedido de {nombre} {v['estado']}", f"Tu pedido de {nombre}{detalle} fue {v['estado']}."
    if v["estado"] == "rechazado" and v.get("motivo_resolucion"):
        cuerpo += f" Motivo: {v['motivo_resolucion']}"
    return _avisar(v["empresa_id"], v["empleado_id"], "vacaciones", titulo, cuerpo,
                   {"movimiento_id": v["id"], "estado": v["estado"], "ruta": "/vacaciones"},
                   f"vacaciones:{v['id']}:{v['estado']}")


# --- Feedback ---------------------------------------------------------------------------------------

def _feedback(feedback_id):
    with db.transaction(read_only=True) as c:
        return db.one(c, """SELECT id, numero, empresa_id, empleado_id, responsable_id, jefe_directo_id, estado,
                                   resolucion_descripcion, motivo_nombre_snapshot AS motivo,
                                   COALESCE(NULLIF(cliente_nombre_fantasia_snapshot, ''),
                                            NULLIF(cliente_razon_social_snapshot, '')) AS cliente
                            FROM feedbacks WHERE id = %s""", (feedback_id,))


@_seguro
def feedback_asignado(feedback_id):
    """Al responsable (jefe directo): tiene un feedback nuevo para resolver."""
    f = _feedback(feedback_id)
    destino = f and (f["responsable_id"] or f["jefe_directo_id"])
    if not destino or int(destino) == int(f["empleado_id"]):
        return 0
    cuerpo = " · ".join(x for x in (f["motivo"], f["cliente"]) if x) or "Revisalo y resolvelo antes del vencimiento."
    return _avisar(f["empresa_id"], int(destino), "feedback_asignado", f"Nuevo feedback para resolver ({f['numero']})",
                   cuerpo, {"feedback_id": f["id"], "ruta": f"/feedback/{f['id']}"}, f"feedback:{f['id']}:asignado")


@_seguro
def feedback_resuelto(feedback_id):
    """Al empleado que lo cargo: ya se resolvio."""
    f = _feedback(feedback_id)
    if not f or f["estado"] != "resuelto":
        return 0
    sobre = f" sobre {f['cliente']}" if f["cliente"] else ""
    cuerpo = f"Tu feedback {f['numero']}{sobre} fue resuelto."
    if f.get("resolucion_descripcion"):
        resolucion = str(f["resolucion_descripcion"]).strip()
        cuerpo += " " + (resolucion if len(resolucion) <= 140 else resolucion[:137].rstrip() + "…")
    return _avisar(f["empresa_id"], f["empleado_id"], "feedback_resuelto", "Feedback resuelto", cuerpo,
                   {"feedback_id": f["id"], "ruta": f"/feedback/{f['id']}"}, f"feedback:{f['id']}:resuelto")


# --- Trivias ----------------------------------------------------------------------------------------

_TRIVIA = {
    "nueva": ("trivia_nueva", "Nueva trivia", "Ya podés jugar «{titulo}». ¡Sumá puntos!"),
    "recordatorio_24h": ("trivia_recordatorio", "Trivia: quedan 24 horas", "Tenés 24 horas para participar en «{titulo}»."),
    "recordatorio_2h": ("trivia_recordatorio", "Trivia: quedan 2 horas", "¡Quedan 2 horas para participar en «{titulo}»!"),
}


@_seguro
def trivia(trivia_row, empleados, momento):
    """momento: nueva | recordatorio_24h | recordatorio_2h. empleados: filas con empleado_id y empresa_id.
    La trivia nueva va tambien a la bandeja; los recordatorios son solo push."""
    tipo, titulo, plantilla = _TRIVIA[momento]
    if momento != "nueva" and not push_service.activo():
        return 0
    cuerpo = plantilla.format(titulo=trivia_row.get("titulo") or "Trivia")
    por_empresa = defaultdict(list)
    for empleado in empleados:
        if empleado.get("empresa_id"):
            por_empresa[int(empleado["empresa_id"])].append(int(empleado["empleado_id"]))
    datos = {"trivia_id": trivia_row["id"], "ruta": f"/trivia/{trivia_row['id']}"}
    return sum(push_service.encolar_ahora(empresa_id, ids, tipo, titulo, cuerpo, datos, f"trivia:{trivia_row['id']}:{momento}")
               for empresa_id, ids in por_empresa.items())


# --- Para RR. HH.: solicitudes nuevas para revisar ----------------------------------------------------

def _aprobadores(c, empresa_id, modulo):
    """Empleados de los usuarios del panel (activos, de la empresa) que pueden aprobar el modulo."""
    from web.auth.decorators import can_access_module  # import tardio: la capa web importa servicios

    filas = db.all_rows(c, """SELECT u.id AS usuario_id, u.empleado_id
                              FROM usuarios u JOIN empleados e ON e.id = u.empleado_id
                              WHERE u.activo = 1 AND u.empresa_id = %s AND e.activo = 1""", (empresa_id,))
    return {int(f["empleado_id"]) for f in filas if can_access_module(f["usuario_id"], modulo, "aprobar")}


def _jefe(c, empleado_id):
    fila = db.one(c, """SELECT j.id FROM empleados e JOIN empleados j ON j.id = e.reporta_a_empleado_id
                        WHERE e.id = %s AND j.activo = 1""", (empleado_id,))
    return {int(fila["id"])} if fila else set()


def destinatarios_revision(c, empresa_id, modulo, solicitante_id, destinatarios):
    ids = set()
    if reglas_push.RRHH in destinatarios:
        ids |= _aprobadores(c, empresa_id, modulo)
    if reglas_push.SEGURIDAD in destinatarios:
        ids |= _aprobadores(c, empresa_id, "seguridad_higiene")
    if reglas_push.JEFE in destinatarios:
        ids |= _jefe(c, solicitante_id)
    ids.discard(int(solicitante_id or 0))  # nunca al que pidio
    return sorted(ids)


# --- Para el panel: a quien no le pueden llegar los avisos de solicitudes ------------------------------

_MODULOS_REVISION = {"justificaciones": "Justificaciones", "vacaciones": "Vacaciones", "pedidos_empleados": "Pedidos",
                     "reintegros": "Viáticos", "epp": "EPP", "seguridad_higiene": "Seguridad e Higiene"}


def _con_app(c, empleado_ids):
    """Empleados con al menos un dispositivo activo (la app instalada y la sesion iniciada)."""
    ids = sorted({int(i) for i in empleado_ids if i})
    if not ids:
        return set()
    marcas = ",".join(["%s"] * len(ids))
    filas = db.all_rows(c, f"SELECT DISTINCT empleado_id FROM push_dispositivos WHERE activo = 1 AND empleado_id IN ({marcas})",
                        tuple(ids))
    return {int(f["empleado_id"]) for f in filas}


def cobertura(empresa_id):
    """Revision de los datos que usan los avisos de solicitudes, con lo mismo que usa destinatarios_revision:
    el «Reporta a» de cada empleado, los dispositivos registrados y los usuarios del panel que pueden aprobar."""
    from web.auth.decorators import can_access_module  # import tardio: la capa web importa servicios

    with db.transaction(read_only=True) as c:
        empleados = db.all_rows(c, """SELECT e.id, e.apellido, e.nombre, e.legajo, e.reporta_a_empleado_id AS jefe_id,
                                             j.apellido AS jefe_apellido, j.nombre AS jefe_nombre, j.activo AS jefe_activo
                                      FROM empleados e LEFT JOIN empleados j ON j.id = e.reporta_a_empleado_id
                                      WHERE e.empresa_id = %s AND e.activo = 1
                                      ORDER BY e.apellido, e.nombre""", (empresa_id,))
        usuarios = db.all_rows(c, """SELECT u.id, u.usuario, u.rol, u.empleado_id, e.apellido, e.nombre,
                                            e.activo AS empleado_activo
                                     FROM usuarios u LEFT JOIN empleados e ON e.id = u.empleado_id
                                     WHERE u.activo = 1 AND u.empresa_id = %s
                                     ORDER BY u.usuario""", (empresa_id,))
        jefes = {}
        sin_jefe = []
        for e in empleados:
            if e["jefe_id"] and e["jefe_activo"]:
                jefe = jefes.setdefault(int(e["jefe_id"]), dict(
                    id=int(e["jefe_id"]), nombre=f"{e['jefe_apellido']} {e['jefe_nombre']}".strip(), a_cargo=0))
                jefe["a_cargo"] += 1
            else:
                sin_jefe.append(dict(id=e["id"], nombre=_nombre(e), legajo=e["legajo"],
                                     motivo="El jefe asignado está inactivo" if e["jefe_id"] else None))
        aprobadores = []
        for u in usuarios:
            modulos = [nombre for modulo, nombre in _MODULOS_REVISION.items() if can_access_module(u["id"], modulo, "aprobar")]
            if modulos:
                vinculado = bool(u["empleado_id"] and u["empleado_activo"])
                aprobadores.append(dict(id=u["id"], usuario=u["usuario"], rol=u["rol"], modulos=modulos,
                                        empleado_id=u["empleado_id"] if vinculado else None,
                                        empleado=_nombre(u) if vinculado else None,
                                        motivo="El empleado vinculado está inactivo" if u["empleado_id"] and not vinculado else None))
        con_app = _con_app(c, list(jefes) + [a["empleado_id"] for a in aprobadores])
    vinculados = [a for a in aprobadores if a["empleado_id"]]
    return dict(
        empleados=len(empleados),
        sin_jefe=sin_jefe,
        jefes=len(jefes),
        jefes_sin_app=sorted((j for j in jefes.values() if j["id"] not in con_app), key=lambda j: j["nombre"]),
        aprobadores=len(aprobadores),
        sin_vincular=[a for a in aprobadores if not a["empleado_id"]],
        aprobadores_sin_app=[a for a in vinculados if a["empleado_id"] not in con_app],
    )


def _para_revisar(modulo, fila, titulo, cuerpo, clave, *, datos=None, clave_regla=None, ids=None):
    """Aviso "para revisar" a quienes indica la regla del modulo. datos se suma a los de siempre (p. ej. la ruta de
    la pantalla del jefe); clave_regla e ids permiten otra regla y otros destinatarios (escalamiento)."""
    clave_regla = clave_regla or f"revision:{modulo}"
    regla = reglas_push.regla(fila["empresa_id"], clave_regla)
    if not regla or not regla["activo"]:
        return 0
    if ids is None:
        with db.transaction(read_only=True) as c:
            ids = destinatarios_revision(c, fila["empresa_id"], modulo, fila["empleado_id"], regla["destinatarios"])
    if not ids:
        return 0
    base = {"modulo": modulo, "registro_id": fila["id"], "ruta": f"/revisiones/{modulo}"}
    return push_service.encolar_ahora(fila["empresa_id"], ids, "revision_pendiente", titulo, cuerpo,
                                      dict(base, **(datos or {})), clave, regla=clave_regla)


def _nombre(fila):
    return f"{fila['apellido']} {fila['nombre']}".strip()


@_seguro
def revision_justificacion(justificacion_id):
    with db.transaction(read_only=True) as c:
        j = db.one(c, """SELECT j.id, j.empleado_id, e.empresa_id, e.apellido, e.nombre, j.estado, j.fecha,
                                j.fecha_desde, j.fecha_hasta, j.motivo
                         FROM justificaciones j JOIN empleados e ON e.id = j.empleado_id WHERE j.id = %s""",
                   (justificacion_id,))
    if not j or j["estado"] != "pendiente":
        return 0
    cuerpo = _nombre(j) + _rango(j["fecha_desde"] or j["fecha"], j["fecha_hasta"] or j["fecha"])
    if j.get("motivo"):
        motivo = str(j["motivo"]).strip()
        cuerpo += " · " + (motivo if len(motivo) <= 80 else motivo[:77].rstrip() + "…")
    return _para_revisar("justificaciones", j, "Justificación para revisar", cuerpo,
                         f"revision:justificaciones:{j['id']}")


@_seguro
def revision_vacaciones(movimiento_id):
    """Compatibilidad: el aviso es por solicitud (un pedido con varias tandas avisa una sola vez)."""
    with db.transaction(read_only=True) as c:
        fila = db.one(c, "SELECT COALESCE(solicitud_id, id) AS sid FROM vacaciones_movimientos WHERE id = %s",
                      (movimiento_id,))
    return revision_vacaciones_solicitud(fila["sid"]) if fila else 0


# --- Vacaciones por solicitud (vacaciones_semanas_service) ---------------------------------------------------

def _tandas_vacaciones(c, sid):
    return db.all_rows(c, """SELECT v.id, v.empresa_id, v.empleado_id, v.estado, v.dias, v.fecha_desde, v.fecha_hasta,
                                    v.cancelacion_pedida_at, v.cancelacion_motivo, v.revertido_por_movimiento_id,
                                    e.apellido, e.nombre, e.reporta_a_empleado_id
                             FROM vacaciones_movimientos v JOIN empleados e ON e.id = v.empleado_id
                             WHERE COALESCE(v.solicitud_id, v.id) = %s AND v.tipo = 'tomado'
                               AND v.origen_movimiento_id IS NULL ORDER BY v.fecha_desde""", (int(sid),))


def _rangos(tandas):
    """'del 13/10 al 26/10 y del 11/01 al 17/01'"""
    partes = [_rango(t["fecha_desde"], t["fecha_hasta"]).strip() for t in tandas]
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def _total_dias(tandas):
    return _dias(sum(abs(Decimal(str(t["dias"] or 0))) for t in tandas))


def _datos_solicitud(sid, ruta, **extra):
    return dict({"solicitud_id": sid, "registro_id": sid, "ruta": ruta}, **extra)


@_seguro
def revision_vacaciones_solicitud(sid):
    """Al jefe directo (y RR. HH. si la regla lo incluye): un aviso por solicitud, con las fechas reales."""
    with db.transaction(read_only=True) as c:
        tandas = [t for t in _tandas_vacaciones(c, sid) if t["estado"] == "pendiente"]
    if not tandas:
        return 0
    dias = sum(int(abs(Decimal(str(t["dias"] or 0)))) for t in tandas)
    semanas = f"{dias // 7} semana{'s' if dias // 7 != 1 else ''}" if dias % 7 == 0 else _dias(dias)
    cuerpo = f"{_nombre(tandas[0])} pidió {semanas}: {_rangos(tandas)} ({_dias(dias)})."
    fila = dict(tandas[0], id=sid)
    return _para_revisar("vacaciones", fila, "Vacaciones para revisar", cuerpo, f"revision:vacaciones:s{sid}:pedido",
                         datos=_datos_solicitud(sid, f"/equipo/vacaciones/{sid}"))


@_seguro
def revision_cancelacion_vacaciones(sid):
    with db.transaction(read_only=True) as c:
        tandas = [t for t in _tandas_vacaciones(c, sid)
                  if t["cancelacion_pedida_at"] and t["estado"] == "aprobado" and not t["revertido_por_movimiento_id"]]
    if not tandas:
        return 0
    cuerpo = f"{_nombre(tandas[0])} pidió cancelar sus vacaciones {_rangos(tandas)}."
    if tandas[0].get("cancelacion_motivo"):
        cuerpo += f" Motivo: {tandas[0]['cancelacion_motivo']}"
    marca = max(t["cancelacion_pedida_at"] for t in tandas)
    fila = dict(tandas[0], id=sid)
    return _para_revisar("vacaciones", fila, "Cancelación de vacaciones para revisar", cuerpo,
                         f"revision:vacaciones:s{sid}:cancelacion:{marca:%Y%m%d%H%M%S}",
                         datos=_datos_solicitud(sid, f"/equipo/vacaciones/{sid}", evento="cancelacion"))


_EVENTOS_VACACIONES = {
    "aprobada": ("Vacaciones aprobadas", "Tus vacaciones {rangos} fueron aprobadas", "aprobado"),
    "rechazada": ("Vacaciones rechazadas", "Tus vacaciones {rangos} fueron rechazadas", "rechazado"),
    "cancelada": ("Vacaciones canceladas", "Se cancelaron tus vacaciones {rangos}", "cancelado"),
    "cancelacion_rechazada": ("Tus vacaciones siguen en pie", "No se aceptó cancelar tus vacaciones {rangos}", "aprobado"),
    "cargada": ("Vacaciones cargadas", "RR. HH. te cargó vacaciones {rangos}", "aprobado"),
}


@_seguro
def vacaciones_solicitud_resuelta(sid, evento, movimiento_ids=None, *, actor=None, motivo=None):
    """Al empleado: aprobada, rechazada, cancelada, cancelacion_rechazada o cargada (un aviso por resolucion)."""
    titulo, plantilla, estado = _EVENTOS_VACACIONES[evento]
    with db.transaction(read_only=True) as c:
        tandas = _tandas_vacaciones(c, sid)
    if movimiento_ids:
        tandas = [t for t in tandas if int(t["id"]) in {int(i) for i in movimiento_ids}]
    if not tandas:
        return 0
    cuerpo = plantilla.format(rangos=_rangos(tandas)) + f" ({_total_dias(tandas)})"
    cuerpo += f" por {actor}." if actor and evento != "cargada" else "."
    if motivo and evento in ("rechazada", "cancelacion_rechazada"):
        cuerpo += f" Motivo: {motivo}"
    ids = "-".join(str(int(t["id"])) for t in tandas)
    return _avisar(tandas[0]["empresa_id"], tandas[0]["empleado_id"], "vacaciones", titulo, cuerpo,
                   _datos_solicitud(sid, f"/vacaciones/{sid}", estado=estado, evento=evento,
                                    movimiento_id=tandas[0]["id"]),
                   f"vacaciones:s{sid}:{evento}:{ids}"[:140])


def limpiar_revision_vacaciones(sid):
    """La solicitud ya no tiene nada por resolver: fuera los push sin enviar y leidas las notificaciones de revision."""
    ahora = now_local().replace(microsecond=0)
    with db.transaction() as c:
        c.execute("""DELETE FROM push_envios WHERE estado IN ('pendiente', 'reintentar')
                     AND (clave LIKE %s OR clave LIKE %s)""", (f"revision:vacaciones:s{int(sid)}:%", f"revision:vacaciones:{int(sid)}:%"))
        c.execute("""UPDATE empleado_notificaciones SET leido_at = %s
                     WHERE tipo = 'revision_pendiente' AND referencia_tipo IN ('vacaciones_solicitud', 'vacaciones')
                       AND referencia_id = %s AND leido_at IS NULL""", (ahora, int(sid)))


def _habil_anterior(fecha, feriados):
    dia = fecha - dt.timedelta(days=1)
    for _ in range(14):
        if dia.weekday() < 5 and dia not in feriados:
            return dia
        dia -= dt.timedelta(days=1)
    return None


def _habil_siguiente(fecha, feriados):
    dia = fecha + dt.timedelta(days=1)
    for _ in range(14):
        if dia.weekday() < 5 and dia not in feriados:
            return dia
        dia += dt.timedelta(days=1)
    return None


_DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _dia_largo(fecha):
    return f"{_DIAS_SEMANA[fecha.weekday()]} {fecha.strftime('%d/%m')}"


@_seguro
def vacaciones_por_empezar(hoy=None):
    """Una vez por dia: el dia habil anterior al inicio, al empleado (vacaciones_inicio) y, si la regla lo incluye, a
    su jefe directo (vacaciones_equipo). Solo push."""
    from services import feriado_service

    if not push_service.activo():
        return 0
    hoy = hoy or now_local().date()
    with db.transaction(read_only=True) as c:
        tandas = db.all_rows(c, """SELECT v.id, v.empresa_id, v.empleado_id, v.fecha_desde, v.fecha_hasta,
                                          COALESCE(v.solicitud_id, v.id) AS sid, e.apellido, e.nombre, e.sucursal_id,
                                          e.reporta_a_empleado_id
                                   FROM vacaciones_movimientos v JOIN empleados e ON e.id = v.empleado_id
                                   WHERE v.tipo = 'tomado' AND v.estado = 'aprobado' AND v.revertido_por_movimiento_id IS NULL
                                     AND v.origen_movimiento_id IS NULL AND e.activo = 1
                                     AND v.fecha_desde BETWEEN %s AND %s""", (hoy + dt.timedelta(days=1), hoy + dt.timedelta(days=14)))
        mapas = {}
        for t in tandas:
            if t["empresa_id"] not in mapas:
                mapas[t["empresa_id"]] = feriado_service.mapa(c, t["empresa_id"])
    total = 0
    for t in tandas:
        feriados = feriado_service.de_sucursal(mapas[t["empresa_id"]], t["sucursal_id"] or 0)
        desde = t["fecha_desde"] if isinstance(t["fecha_desde"], dt.date) else dt.date.fromisoformat(str(t["fecha_desde"]))
        hasta = t["fecha_hasta"] if isinstance(t["fecha_hasta"], dt.date) else dt.date.fromisoformat(str(t["fecha_hasta"]))
        if _habil_anterior(desde, feriados) != hoy:
            continue
        regla = reglas_push.regla(t["empresa_id"], "vacaciones_inicio")
        if not regla or not regla["activo"]:
            continue
        vuelta = _habil_siguiente(hasta, feriados)
        datos = _datos_solicitud(t["sid"], f"/vacaciones/{t['sid']}", movimiento_id=t["id"])
        if reglas_push.EMPLEADO in regla["destinatarios"]:
            cuerpo = f"Tus vacaciones empiezan el {_dia_largo(desde)}." + (f" Volvés el {_dia_largo(vuelta)}." if vuelta else "")
            total += _avisar(t["empresa_id"], t["empleado_id"], "vacaciones_inicio", "¡Buenas vacaciones!", cuerpo, datos,
                             f"vacaciones-inicio:{t['id']}")
        if reglas_push.JEFE in regla["destinatarios"] and t["reporta_a_empleado_id"]:
            cuerpo = f"{_nombre(t)} sale de vacaciones el {_dia_largo(desde)}" + (
                f" y vuelve el {_dia_largo(vuelta)}." if vuelta else ".")
            total += _avisar(t["empresa_id"], t["reporta_a_empleado_id"], "vacaciones_equipo", "Vacaciones en tu equipo",
                             cuerpo, dict(datos, ruta=f"/equipo/vacaciones/{t['sid']}"), f"vacaciones-equipo:{t['id']}")
    return total


@_seguro
def vacaciones_sin_resolver(hoy=None):
    """Una vez por dia: una solicitud pendiente a N dias (o menos) de empezar se escala, una sola vez, al jefe del jefe
    directo y/o a RR. HH. segun la regla vacaciones_escalar."""
    hoy = hoy or now_local().date()
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, """SELECT COALESCE(v.solicitud_id, v.id) AS sid, MIN(v.fecha_desde) AS desde,
                                         v.empresa_id, v.empleado_id, e.apellido, e.nombre, j.reporta_a_empleado_id AS superior_id
                                  FROM vacaciones_movimientos v JOIN empleados e ON e.id = v.empleado_id
                                  LEFT JOIN empleados j ON j.id = e.reporta_a_empleado_id AND j.activo = 1
                                  WHERE v.tipo = 'tomado' AND v.estado = 'pendiente' AND v.origen_movimiento_id IS NULL
                                    AND v.fecha_desde >= %s AND v.fecha_desde <= %s
                                  GROUP BY COALESCE(v.solicitud_id, v.id), v.empresa_id, v.empleado_id, e.apellido, e.nombre,
                                           j.reporta_a_empleado_id""", (hoy, hoy + dt.timedelta(days=31)))
    total = 0
    for f in filas:
        regla = reglas_push.regla(f["empresa_id"], "vacaciones_escalar")
        if not regla or not regla["activo"]:
            continue
        desde = f["desde"] if isinstance(f["desde"], dt.date) else dt.date.fromisoformat(str(f["desde"]))
        if (desde - hoy).days > int(regla["parametro"] or 0):
            continue
        ids = set()
        if reglas_push.JEFE_SUPERIOR in regla["destinatarios"] and f["superior_id"]:
            ids.add(int(f["superior_id"]))
        if reglas_push.RRHH in regla["destinatarios"]:
            with db.transaction(read_only=True) as c:
                ids |= _aprobadores(c, f["empresa_id"], "vacaciones")
        ids.discard(int(f["empleado_id"]))
        if not ids:
            continue
        cuerpo = (f"{_nombre(f)} empieza sus vacaciones el {_dia_largo(desde)} y la solicitud sigue sin respuesta "
                  f"de su jefe directo.")
        total += _para_revisar("vacaciones", dict(f, id=f["sid"]), "Vacaciones sin resolver", cuerpo,
                               f"revision:vacaciones:s{f['sid']}:escalada",
                               datos=_datos_solicitud(f["sid"], f"/equipo/vacaciones/{f['sid']}", evento="escalada"),
                               clave_regla="vacaciones_escalar", ids=sorted(ids))
    return total


@_seguro
def revision_adelanto(adelanto_id):
    with db.transaction(read_only=True) as c:
        a = db.one(c, """SELECT a.id, a.empresa_id, a.empleado_id, e.apellido, e.nombre, a.estado, a.periodo_month
                         FROM adelantos a JOIN empleados e ON e.id = a.empleado_id WHERE a.id = %s""", (adelanto_id,))
    if not a or a["estado"] != "pendiente":
        return 0
    return _para_revisar("pedidos_empleados", a, "Adelanto para revisar",
                         f"{_nombre(a)} pidió el adelanto de {_MESES[int(a['periodo_month']) - 1]}.",
                         f"revision:adelanto:{a['id']}")


@_seguro
def revision_pedido_mercaderia(pedido_id):
    with db.transaction(read_only=True) as c:
        p = db.one(c, """SELECT p.id, p.empresa_id, p.empleado_id, e.apellido, e.nombre, p.estado, p.periodo_month
                         FROM pedidos_mercaderia p JOIN empleados e ON e.id = p.empleado_id WHERE p.id = %s""",
                   (pedido_id,))
    if not p or p["estado"] != "pendiente":
        return 0
    return _para_revisar("pedidos_empleados", p, "Pedido de mercadería para revisar",
                         f"{_nombre(p)} cargó el pedido de {_MESES[int(p['periodo_month']) - 1]}.",
                         f"revision:mercaderia:{p['id']}")


@_seguro
def revision_reintegro(solicitud_id):
    with db.transaction(read_only=True) as c:
        r = db.one(c, """SELECT r.id, r.empresa_id, r.empleado_id, e.apellido, e.nombre, r.estado, r.revision,
                                r.total_solicitado
                         FROM reintegro_solicitudes r JOIN empleados e ON e.id = r.empleado_id WHERE r.id = %s""",
                   (solicitud_id,))
    if not r or r["estado"] != "pendiente":
        return 0
    return _para_revisar("reintegros", r, "Viáticos para revisar",
                         f"{_nombre(r)} · rendición N° {r['id']} por {_pesos(r['total_solicitado'])}",
                         f"revision:reintegros:{r['id']}:r{r['revision']}")


@_seguro
def revision_epp(pedido_id):
    with db.transaction(read_only=True) as c:
        p = db.one(c, """SELECT p.id, p.empresa_id, p.empleado_id, e.apellido, e.nombre, p.estado, p.revision
                         FROM epp_pedidos p JOIN empleados e ON e.id = p.empleado_id WHERE p.id = %s""", (pedido_id,))
    if not p or p["estado"] != "pendiente":
        return 0
    return _para_revisar("epp", p, "Pedido de EPP para revisar", f"{_nombre(p)} · pedido N° {p['id']}",
                         f"revision:epp:{p['id']}:r{p['revision']}")


# --- Seguridad e Higiene ------------------------------------------------------------------------------

def _tipo_sh(tipo):
    from services.seguridad_service import TIPOS  # import tardio: seguridad_service usa estos avisos

    return TIPOS.get(tipo, tipo)


@_seguro
def revision_seguridad(evento_id):
    """Reporte nuevo cargado por un empleado: al responsable de Seguridad e Higiene (y al jefe, si la regla lo pide)."""
    with db.transaction(read_only=True) as c:
        e = db.one(c, """SELECT ev.id, ev.empresa_id, ev.reportante_id AS empleado_id, ev.tipo, ev.categoria_nombre,
                                ev.fecha_evento, ev.estado, emp.apellido, emp.nombre
                         FROM sh_eventos ev JOIN empleados emp ON emp.id = ev.reportante_id
                         WHERE ev.id = %s""", (evento_id,))
    if not e or e["estado"] != "pendiente":
        return 0
    cuerpo = f"{_nombre(e)} · {_tipo_sh(e['tipo'])}"
    if e.get("categoria_nombre"):
        cuerpo += f" · {e['categoria_nombre']}"
    cuerpo += f" ({_dia(e['fecha_evento'])})"
    return _para_revisar("seguridad_higiene", e, "Reporte de seguridad para revisar", cuerpo,
                         f"revision:seguridad:{e['id']}")


@_seguro
def seguridad_resultado(evento_id):
    """A quien reporto: su reporte fue aprobado o rechazado."""
    with db.transaction(read_only=True) as c:
        e = db.one(c, "SELECT id, empresa_id, reportante_id, tipo, estado, motivo FROM sh_eventos WHERE id = %s",
                   (evento_id,))
    if not e or not e["reportante_id"] or e["estado"] not in ("aprobado", "rechazado"):
        return 0
    cuerpo = f"Tu reporte de {_tipo_sh(e['tipo']).lower()} fue {e['estado']}."
    if e["estado"] == "rechazado" and e.get("motivo"):
        cuerpo += f" Motivo: {e['motivo']}"
    return _avisar(e["empresa_id"], e["reportante_id"], "seguridad_resultado", f"Reporte de seguridad {e['estado']}",
                   cuerpo, {"evento_id": e["id"], "estado": e["estado"], "ruta": f"/seguridad/{e['id']}"},
                   f"seguridad:{e['id']}:{e['estado']}")


def _accion_texto(descripcion):
    texto = " ".join(str(descripcion or "").split())
    return texto if len(texto) <= 100 else texto[:97].rstrip() + "…"


@_seguro
def seguridad_accion(accion_id):
    """Al responsable de una accion correctiva cuando se la asignan (o se la reasignan)."""
    with db.transaction(read_only=True) as c:
        a = db.one(c, """SELECT a.id, a.evento_id, a.descripcion, a.responsable_id, a.vencimiento, a.estado, ev.empresa_id
                         FROM sh_acciones a JOIN sh_eventos ev ON ev.id = a.evento_id WHERE a.id = %s""", (accion_id,))
    if not a or a["estado"] not in ("pendiente", "en_curso"):
        return 0
    return _avisar(a["empresa_id"], a["responsable_id"], "seguridad_accion", "Acción de seguridad asignada",
                   f"{_accion_texto(a['descripcion'])} · vence el {_dia(a['vencimiento'])}",
                   {"accion_id": a["id"], "evento_id": a["evento_id"], "ruta": f"/seguridad/{a['evento_id']}"},
                   f"sh-accion:{a['id']}:{a['responsable_id']}")


@_seguro
def acciones_por_vencer(hoy=None):
    """Una vez por dia: al responsable, N dias antes del vencimiento (regla seguridad_accion) y el dia despues
    si la accion sigue abierta. Recordatorio: solo push, sin bandeja (la asignacion ya esta en la bandeja)."""
    if not push_service.activo():
        return 0
    hoy = hoy or now_local().date()
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, """SELECT a.id, a.evento_id, a.descripcion, a.responsable_id, a.vencimiento, ev.empresa_id
                                  FROM sh_acciones a JOIN sh_eventos ev ON ev.id = a.evento_id
                                  WHERE a.estado IN ('pendiente', 'en_curso') AND a.vencimiento BETWEEN %s AND %s""",
                            (hoy - dt.timedelta(days=1), hoy + dt.timedelta(days=31)))
    total = 0
    for a in filas:
        vencimiento = a["vencimiento"] if isinstance(a["vencimiento"], dt.date) else dt.date.fromisoformat(str(a["vencimiento"]))
        faltan = (vencimiento - hoy).days
        texto = _accion_texto(a["descripcion"])
        if faltan == reglas_push.parametro(a["empresa_id"], "seguridad_accion"):
            cuando = "hoy" if faltan == 0 else ("mañana" if faltan == 1 else f"el {_dia(vencimiento)}")
            titulo, cuerpo, clave = "Acción de seguridad por vencer", f"{texto} · vence {cuando}", f"sh-accion:{a['id']}:vence:{vencimiento}"
        elif faltan == -1:
            titulo, cuerpo, clave = "Acción de seguridad vencida", f"{texto} · venció ayer", f"sh-accion:{a['id']}:vencida:{vencimiento}"
        else:
            continue
        total += _avisar(a["empresa_id"], a["responsable_id"], "seguridad_accion", titulo, cuerpo,
                         {"accion_id": a["id"], "evento_id": a["evento_id"], "ruta": f"/seguridad/{a['evento_id']}"}, clave,
                         bandeja=False)
    return total
