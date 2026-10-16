"""Avisos push al empleado fuera de Reuniones (solo con Firebase configurado; nunca rompen la accion).

- Salida pendiente: la jornada de hoy sigue abierta 30 min despues de la salida prevista (scheduler cada 5 min).
- Resoluciones: EPP (aprobado, aprobado con menos, rechazado, entregado), viaticos y reintegros (aprobada,
  rechazada, devuelta, pagada), adelantos y pedidos de mercaderia (aprobado, rechazado).
- Recordatorio mensual de viaticos (dia 5) por push ademas del aviso dentro de la app.

Cada aviso lleva data.tipo, data.ruta (pantalla a abrir) y el id del registro."""

import logging

from repositories import carga_repository as db
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
        if fin >= egreso.FIN_DEL_DIA or minuto < fin + MARGEN_SALIDA_MIN:
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

