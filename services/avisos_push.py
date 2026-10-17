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


def _avisar(empresa_id, empleado_id, tipo, titulo, cuerpo, datos, clave):
    return push_service.encolar_ahora(empresa_id, [empleado_id], tipo, titulo, cuerpo, datos, clave)


def _seguro(funcion):
    """Un aviso que falla (consulta, tabla) se registra y no interrumpe la accion del panel o la app."""
    def envoltura(*args, **kwargs):
        if not push_service.activo():
            return 0
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
    """Dia 5: el mismo recordatorio que ve la app, por push, a quien todavia no lo leyo."""
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
        v = db.one(c, """SELECT id, empresa_id, empleado_id, tipo, estado, dias, fecha_desde, fecha_hasta,
                                motivo_resolucion
                         FROM vacaciones_movimientos WHERE id = %s""", (movimiento_id,))
    if not v or v["estado"] not in ("aprobado", "rechazado"):
        return 0
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
    """momento: nueva | recordatorio_24h | recordatorio_2h. empleados: filas con empleado_id y empresa_id."""
    tipo, titulo, plantilla = _TRIVIA[momento]
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


def _para_revisar(modulo, fila, titulo, cuerpo, clave):
    clave_regla = f"revision:{modulo}"
    regla = reglas_push.regla(fila["empresa_id"], clave_regla)
    if not regla or not regla["activo"]:
        return 0
    with db.transaction(read_only=True) as c:
        ids = destinatarios_revision(c, fila["empresa_id"], modulo, fila["empleado_id"], regla["destinatarios"])
    if not ids:
        return 0
    datos = {"modulo": modulo, "registro_id": fila["id"], "ruta": f"/revisiones/{modulo}"}
    return push_service.encolar_ahora(fila["empresa_id"], ids, "revision_pendiente", titulo, cuerpo, datos, clave,
                                      regla=clave_regla)


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
    with db.transaction(read_only=True) as c:
        v = db.one(c, """SELECT v.id, v.empresa_id, v.empleado_id, e.apellido, e.nombre, v.estado, v.dias,
                                v.fecha_desde, v.fecha_hasta
                         FROM vacaciones_movimientos v JOIN empleados e ON e.id = v.empleado_id WHERE v.id = %s""",
                   (movimiento_id,))
    if not v or v["estado"] != "pendiente":
        return 0
    cuerpo = f"{_nombre(v)}{_rango(v['fecha_desde'], v['fecha_hasta'])} ({_dias(abs(Decimal(str(v['dias'] or 0))))})"
    return _para_revisar("vacaciones", v, "Vacaciones para revisar", cuerpo, f"revision:vacaciones:{v['id']}")


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
    si la accion sigue abierta."""
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
                         {"accion_id": a["id"], "evento_id": a["evento_id"], "ruta": f"/seguridad/{a['evento_id']}"}, clave)
    return total
