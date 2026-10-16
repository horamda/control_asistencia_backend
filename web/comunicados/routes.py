"""Comunicados: envio desde el panel (aviso push + bandeja en la app) y API del empleado."""

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from routes.carga_routes import employee
from services import comunicado_service as s
from utils.audit import log_audit
from utils.jwt_guard import mobile_auth_required
from web.auth.decorators import _cached_web_user, permission_required
# Mismo selector de destinatarios que Reuniones (sucursales, sectores/puestos y personas).
from web.reuniones.routes import _form_context as _contexto_destinatarios

web = Blueprint("comunicados", __name__, url_prefix="/comunicados")
mobile = Blueprint("comunicados_mobile", __name__, url_prefix="/api/v1/mobile/comunicados")


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


@web.errorhandler(s.Error)
@mobile.errorhandler(s.Error)
def invalid(error):
    if request.blueprint == "comunicados_mobile":
        return jsonify(error=str(error)), error.status
    flash(str(error), "error")
    return redirect(url_for("comunicados.index"))


@web.errorhandler(ProgrammingError)
@mobile.errorhandler(ProgrammingError)
def missing(error):
    if error.errno not in (1146, 1054):
        raise error
    return invalid(s.Error("Comunicados requiere la migración 20261016_06_comunicados (se aplica al reiniciar).", 503))


@web.after_request
@mobile.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


# --- Panel -------------------------------------------------------------------------------------

def _form_data():
    form = request.form
    sucursales = form.getlist("sede")
    return dict(titulo=form.get("titulo", ""), mensaje=form.get("mensaje", ""), reglas=form.getlist("regla"),
                empleados=form.getlist("empleado"), sucursales=sucursales,
                sedes=[dict(sucursal_id=x) for x in sucursales])


def _form(actor, data=None, status=200):
    contexto = _contexto_destinatarios(actor, data=data)
    return render_template("comunicados/form.html", v=data or {}, **contexto), status


@web.get("/")
@permission_required("comunicados", "ver")
def index():
    return render_template("comunicados/index.html", **s.listado(who(), request.args.get("page", 1, type=int)))


@web.route("/nuevo", methods=["GET", "POST"])
@permission_required("comunicados", "crear")
def nuevo():
    actor = who()
    if request.method == "GET":
        return _form(actor)
    data = _form_data()
    try:
        cid, total = s.enviar(actor, data)
    except s.Error as error:
        flash(str(error), "error")
        return _form(actor, data, 400)
    log_audit(session, "comunicado_enviar", "comunicados", cid)
    flash(f"Comunicado enviado a {total} empleado{'' if total == 1 else 's'}. "
          "Quien tenga la app con notificaciones lo recibe en unos minutos; el resto lo ve en su bandeja.", "success")
    return redirect(url_for("comunicados.detalle", comunicado_id=cid))


@web.get("/<int:comunicado_id>")
@permission_required("comunicados", "ver")
def detalle(comunicado_id):
    estado = request.args.get("estado") if request.args.get("estado") in ("leidos", "pendientes") else None
    return render_template("comunicados/detalle.html", **s.detalle(who(), comunicado_id, estado))


@web.post("/<int:comunicado_id>/eliminar")
@permission_required("comunicados", "eliminar")
def eliminar(comunicado_id):
    comunicado = s.eliminar(who(), comunicado_id)
    log_audit(session, "comunicado_eliminar", "comunicados", comunicado_id)
    flash(f"Se quitó «{comunicado['titulo']}» de la bandeja de la app.", "success")
    return redirect(url_for("comunicados.index"))


# --- App del empleado -----------------------------------------------------------------------------

@mobile.get("")
@mobile_auth_required
def mis_comunicados():
    return jsonify(s.mis_comunicados(employee(), request.args.get("page", 1, type=int)))


@mobile.get("/<int:comunicado_id>")
@mobile_auth_required
def ver(comunicado_id):
    """Devuelve el comunicado y lo marca como leido."""
    return jsonify(s.leer(employee(), comunicado_id))


@mobile.post("/<int:comunicado_id>/leido")
@mobile_auth_required
def leido(comunicado_id):
    return jsonify(s.leer(employee(), comunicado_id))


@mobile.post("/leer-todos")
@mobile_auth_required
def leer_todos():
    return jsonify(marcados=s.leer_todos(employee()))
