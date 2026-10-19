"""Panel: horas extras (jornada laboral, etapa C). Bandeja de autorizacion en dos pasos, cierre del mes y liquidacion.

Permiso horas_extras: ver; aprobar (jefe: visto bueno de su cadena; RR. HH.: decision); editar (RR. HH.: cerrar y
reabrir el mes); exportar (RR. HH.: liquidacion). RR. HH. = rol admin o rrhh. Ver docs/jornada_laboral.md."""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from services import horas_extras_service as he
from services import jornada_calculo_service as calc
from services.table_export_service import build_attachment_response
from utils.audit import log_audit
from web.auth.decorators import _cached_web_user, can_access_module, permission_required
from web.horas.routes import XLSX, _opciones

web = Blueprint("horas_extras", __name__, url_prefix="/horas-extras")
FILTROS = ("sucursal_id", "sector_id", "convenio_id")
VISTAS = {"decidir": "Para decidir", "todas": "Todas", "aprobada": "Aprobadas", "rechazada": "Rechazadas",
          "liquidada": "Liquidadas"}


def actor():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo") or not user.get("empresa_id"):
        abort(403)
    rol = str(user.get("rol") or "").strip().lower()
    return dict(empresa_id=user["empresa_id"], user_id=user["id"], empleado_id=user.get("empleado_id"),
                **{"global": rol in ("admin", "rrhh")},
                aprobar=can_access_module(user["id"], "horas_extras", "aprobar"),
                editar=can_access_module(user["id"], "horas_extras", "editar"),
                exportar=can_access_module(user["id"], "horas_extras", "exportar"))


@web.errorhandler(he.Error)
def invalido(error):
    flash(str(error), "error")
    return redirect(request.referrer or url_for("horas_extras.bandeja"))


@web.errorhandler(ProgrammingError)
def sin_migrar(error):
    if error.errno not in (1146, 1054):
        raise error
    return render_template("error.html", code=503, request_id=None,
                           message="Horas extras requiere su migración (20261019_horas_extras); se aplica al reiniciar "
                                   "el servicio."), 503


@web.after_request
def privado(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _mes():
    valor = request.values.get("mes") or calc._hoy().strftime("%Y-%m")
    he.mes_de(valor)
    return valor[:7]


def _volver(defecto):
    """Solo rutas del mismo sitio (nunca una URL externa)."""
    destino = str(request.form.get("volver") or "")
    return destino if destino.startswith("/") and not destino.startswith("//") and "\\" not in destino else defecto


def _comunes(quien):
    return dict(ESTADOS=he.ESTADOS, ACCIONES=he.ACCIONES, DIAS_CORTOS=calc.DIAS_CORTOS, quien=quien)


@web.get("/")
@permission_required("horas_extras", "ver")
def bandeja():
    quien = actor()
    mes = _mes()
    filtros = {k: request.args.get(k, "") for k in FILTROS}
    datos = he.bandeja(quien, mes, filtros)
    vista = request.args.get("vista") if request.args.get("vista") in VISTAS else "decidir"
    if vista == "decidir":
        items = [i for i in datos["items"] if (i["puede"] == ("jefe",) and i["estado"] == "pendiente")
                 or (i["puede"] == ("rrhh",) and i["estado"] in ("pendiente", "visto_jefe", "rechazo_jefe"))]
    elif vista == "todas":
        items = datos["items"]
    else:
        items = [i for i in datos["items"] if i["estado"] == vista]
    conteo = {v: sum(1 for i in datos["items"] if i["estado"] == v) for v in ("aprobada", "rechazada", "liquidada")}
    return render_template("horas_extras/bandeja.html", datos=datos, items=items, vista=vista, VISTAS=VISTAS, conteo=conteo,
                           mes=mes, filtros=filtros, args={"mes": mes, **{k: v for k, v in filtros.items() if v}},
                           **_opciones(quien["empresa_id"]), **_comunes(quien))


@web.get("/dia/<int:empleado_id>/<fecha>")
@permission_required("horas_extras", "ver")
def dia(empleado_id, fecha):
    quien = actor()
    return render_template("horas_extras/dia.html", **he.detalle(quien, empleado_id, fecha), mes=str(fecha)[:7],
                           **_comunes(quien))


@web.post("/dia/<int:empleado_id>/<fecha>")
@permission_required("horas_extras", "aprobar")
def decidir(empleado_id, fecha):
    quien = actor()
    accion = request.form.get("accion")
    hid = he.decidir(quien, empleado_id, fecha, accion, request.form.get("minutos_habil"),
                     request.form.get("minutos_descanso"), request.form.get("motivo"),
                     request.form.get("confirmar_tope") == "1")
    log_audit(session, f"horas_extra_{accion}", "jl_horas_extra", hid)
    flash(f"{he.ACCIONES[accion]} registrado.", "success")
    return redirect(_volver(url_for("horas_extras.dia", empleado_id=empleado_id, fecha=fecha)))


@web.post("/lote")
@permission_required("horas_extras", "aprobar")
def lote():
    quien = actor()
    claves = [v.split("|", 1) for v in request.form.getlist("dia") if "|" in v]
    hechos, errores = he.decidir_lote(quien, _mes(), claves, request.form.get("accion"))
    log_audit(session, f"horas_extra_lote_{request.form.get('accion')}", "jl_horas_extra", None)
    if hechos:
        flash(f"{he.ACCIONES[request.form.get('accion')]}: {hechos} día{'' if hechos == 1 else 's'}.", "success")
    for e in errores[:10]:
        flash(f"{e.get('nombre') or e['clave'][0]} {e['clave'][1]:%d/%m}: {e['error']}", "error")
    return redirect(_volver(url_for("horas_extras.bandeja", mes=_mes())))


@web.get("/cierre")
@permission_required("horas_extras", "ver")
def cierre():
    quien = actor()
    if not quien["global"]:
        abort(403)
    mes = _mes()
    return render_template("horas_extras/cierre.html", estado=he.estado_cierre(quien, mes), mes=mes,
                           periodos=he.periodos(quien["empresa_id"]), **_comunes(quien))


@web.post("/cierre/cerrar")
@permission_required("horas_extras", "editar")
def cerrar():
    quien = actor()
    mes = _mes()
    pid, liquidadas = he.cerrar(quien, mes)
    log_audit(session, "horas_extra_cerrar_mes", "jl_periodos", pid)
    flash(f"Mes cerrado. {liquidadas} día{'' if liquidadas == 1 else 's'} con horas extras pasaron a liquidadas.", "success")
    return redirect(url_for("horas_extras.cierre", mes=mes))


@web.post("/cierre/reabrir")
@permission_required("horas_extras", "editar")
def reabrir():
    quien = actor()
    mes = _mes()
    pid, _ = he.reabrir(quien, mes, request.form.get("motivo"))
    log_audit(session, "horas_extra_reabrir_mes", "jl_periodos", pid)
    flash("Mes reabierto: las horas liquidadas volvieron a aprobadas. La reapertura queda registrada.", "success")
    return redirect(url_for("horas_extras.cierre", mes=mes))


@web.get("/cierre/liquidacion")
@permission_required("horas_extras", "exportar")
def liquidacion():
    quien = actor()
    mes = _mes()
    datos = he.liquidacion(quien, mes)
    log_audit(session, "horas_extra_exportar_liquidacion", "jl_periodos", datos["periodo"]["id"])
    return build_attachment_response(he.exportar_liquidacion(datos), filename=f"liquidacion_horas_{mes.replace('-', '')}.xlsx",
                                     mimetype=XLSX)
