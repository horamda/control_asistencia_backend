"""Panel: banco de horas (jornada laboral, etapa D). Acuerdos por empleado y libro de movimientos.

Permiso banco_horas: ver (saldos y libro), editar (acuerdos, movimientos manuales, francos y reversiones).
Ver docs/jornada_laboral.md."""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from services import banco_horas_service as bh
from services import jornada_calculo_service as calc
from utils.audit import log_audit
from web.auth.decorators import _cached_web_user, permission_required
from web.horas.routes import _opciones

web = Blueprint("banco_horas", __name__, url_prefix="/banco-horas")


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo") or not user.get("empresa_id"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


@web.errorhandler(bh.Error)
def invalido(error):
    flash(str(error), "error")
    if getattr(error, "status", 400) == 404:
        return redirect(url_for("banco_horas.resumen"))
    return redirect(request.referrer or url_for("banco_horas.resumen"))


@web.errorhandler(ProgrammingError)
def sin_migrar(error):
    if error.errno not in (1146, 1054):
        raise error
    return render_template("error.html", code=503, request_id=None,
                           message="El banco de horas requiere su migración (20261019_banco_horas); se aplica al "
                                   "reiniciar el servicio."), 503


@web.after_request
def privado(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _comunes():
    return dict(TIPOS=bh.TIPOS, DEL_CIERRE=bh.DEL_CIERRE, hoy=calc._hoy().isoformat())


@web.get("/")
@permission_required("banco_horas", "ver")
def resumen():
    actor = who()
    filtros = {k: request.args.get(k, "") for k in ("sucursal_id", "sector_id")}
    opciones = _opciones(actor["empresa_id"])
    with bh.db.transaction(read_only=True) as c:
        empleados = bh.db.all_rows(c, """SELECT id, apellido, nombre, legajo FROM empleados WHERE empresa_id = %s AND activo = 1
                                         ORDER BY apellido, nombre""", (actor["empresa_id"],))
    return render_template("banco_horas/resumen.html", filas=bh.resumen(actor["empresa_id"], filtros), filtros=filtros,
                           todos=empleados, sucursales=opciones["sucursales"], sectores=opciones["sectores"], **_comunes())


@web.get("/ir")
@permission_required("banco_horas", "ver")
def ir():
    empleado_id = request.args.get("empleado_id", "")
    if not empleado_id.isdigit():
        return redirect(url_for("banco_horas.resumen"))
    return redirect(url_for("banco_horas.empleado", empleado_id=int(empleado_id)))


@web.get("/empleado/<int:empleado_id>")
@permission_required("banco_horas", "ver")
def empleado(empleado_id):
    return render_template("banco_horas/empleado.html", **bh.detalle(who(), empleado_id), **_comunes())


@web.post("/empleado/<int:empleado_id>/acuerdo")
@permission_required("banco_horas", "editar")
def acuerdo(empleado_id):
    aid = bh.guardar_acuerdo(who(), empleado_id, request.form)
    log_audit(session, "banco_horas_acuerdo", "jl_banco_acuerdos", aid)
    flash("Acuerdo guardado. La versión anterior queda en el historial.", "success")
    return redirect(url_for("banco_horas.empleado", empleado_id=empleado_id))


@web.post("/empleado/<int:empleado_id>/acuerdo/finalizar")
@permission_required("banco_horas", "editar")
def finalizar(empleado_id):
    aid = bh.finalizar_acuerdo(who(), empleado_id, request.form.get("vigente_hasta"), request.form.get("motivo"))
    log_audit(session, "banco_horas_acuerdo_finalizar", "jl_banco_acuerdos", aid)
    flash("Acuerdo finalizado. El saldo se conserva y se puede seguir usando en francos.", "success")
    return redirect(url_for("banco_horas.empleado", empleado_id=empleado_id))


@web.post("/empleado/<int:empleado_id>/movimiento")
@permission_required("banco_horas", "editar")
def movimiento(empleado_id):
    tipo = request.form.get("tipo")
    mid = bh.registrar(who(), empleado_id, tipo, request.form.get("fecha"), request.form.get("horas"),
                       request.form.get("motivo"), request.form.get("dia_completo") == "1")
    log_audit(session, f"banco_horas_{tipo}", "jl_banco_movimientos", mid)
    flash(f"{bh.TIPOS.get(tipo, 'Movimiento')} registrado.", "success")
    return redirect(url_for("banco_horas.empleado", empleado_id=empleado_id))


@web.post("/movimiento/<int:movimiento_id>/revertir")
@permission_required("banco_horas", "editar")
def revertir(movimiento_id):
    actor = who()
    mid = bh.revertir(actor, movimiento_id, request.form.get("motivo"))
    log_audit(session, "banco_horas_reversion", "jl_banco_movimientos", mid)
    flash("Movimiento revertido: queda la reversión en el libro.", "success")
    with bh.db.transaction(read_only=True) as c:
        fila = bh.db.one(c, "SELECT empleado_id FROM jl_banco_movimientos WHERE id = %s", (mid,))
    return redirect(url_for("banco_horas.empleado", empleado_id=fila["empleado_id"]))
