"""Comunicados: envio desde el panel (aviso push + bandeja en la app) y API del empleado."""

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from routes.carga_routes import employee, private_photo
from services import comunicado_programado_service as programados
from services import comunicado_service as s
from services import push_reglas_service as reglas_push
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
    return invalid(s.Error("Comunicados requiere sus migraciones (20261016_06 y 20261017_01); se aplican al reiniciar.", 503))


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
                sedes=[dict(sucursal_id=x) for x in sucursales],
                # Programacion (si se eligio "Programar"); se devuelve al formulario si hay un error.
                cuando=form.get("cuando", "ahora"), frecuencia=form.get("frecuencia", "una_vez"),
                fecha_inicio=form.get("fecha_inicio", ""), hora=form.get("hora", ""),
                dias_semana=form.getlist("dias_semana"), dia_mes=form.get("dia_mes", ""),
                solo_habiles=bool(form.get("solo_habiles")), termina=form.get("termina", "nunca"),
                fecha_fin=form.get("fecha_fin", ""), max_envios=form.get("max_envios", ""))


def _form(actor, data=None, status=200):
    contexto = _contexto_destinatarios(actor, data=data)
    return render_template("comunicados/form.html", v=data or {}, frecuencias=programados.FRECUENCIAS,
                           dias_nombres=programados.DIAS, hoy=s.now_local().date().isoformat(), **contexto), status


@web.get("/")
@permission_required("comunicados", "ver")
def index():
    return render_template("comunicados/index.html", **s.listado(who(), request.args.get("page", 1, type=int)))


@web.get("/automaticos")
@permission_required("comunicados", "ver")
def automaticos():
    return render_template("comunicados/automaticos.html", **s.automaticos(who(), request.args))


@web.get("/programados")
@permission_required("comunicados", "ver")
def lista_programados():
    return render_template("comunicados/programados.html", **programados.listado(who()))


@web.post("/programados/<int:programado_id>/pausar")
@permission_required("comunicados", "crear")
def pausar_programado(programado_id):
    prog = programados.pausar(who(), programado_id)
    log_audit(session, "comunicado_programado_pausar", "comunicados_programados", programado_id)
    flash(f"«{prog['titulo']}» quedó en pausa.", "success")
    return redirect(url_for("comunicados.lista_programados"))


@web.post("/programados/<int:programado_id>/reanudar")
@permission_required("comunicados", "crear")
def reanudar_programado(programado_id):
    prog, siguiente = programados.reanudar(who(), programado_id)
    log_audit(session, "comunicado_programado_reanudar", "comunicados_programados", programado_id)
    flash(f"«{prog['titulo']}» se reanudó. Próximo envío: {siguiente:%d/%m/%Y a las %H:%M}." if siguiente
          else f"«{prog['titulo']}» ya no tiene envíos por hacer: quedó finalizado.", "success")
    return redirect(url_for("comunicados.lista_programados"))


@web.post("/programados/<int:programado_id>/eliminar")
@permission_required("comunicados", "eliminar")
def eliminar_programado(programado_id):
    prog = programados.eliminar(who(), programado_id)
    log_audit(session, "comunicado_programado_eliminar", "comunicados_programados", programado_id)
    flash(f"Se eliminó la programación «{prog['titulo']}». Lo ya enviado sigue en Enviados.", "success")
    return redirect(url_for("comunicados.lista_programados"))


@web.route("/configuracion", methods=["GET", "POST"])
@permission_required("comunicados", "editar")
def configuracion():
    actor = who()
    if request.method == "POST":
        try:
            reglas_push.guardar(actor, request.form)
        except s.Error as error:
            flash(str(error), "error")
            return render_template("comunicados/configuracion.html", **reglas_push.vista(actor)), 400
        log_audit(session, "push_reglas_guardar", "push_reglas", actor["empresa_id"])
        flash("Configuración de avisos guardada. Rige para los avisos nuevos.", "success")
        return redirect(url_for("comunicados.configuracion"))
    return render_template("comunicados/configuracion.html", **reglas_push.vista(actor))


@web.route("/nuevo", methods=["GET", "POST"])
@permission_required("comunicados", "crear")
def nuevo():
    actor = who()
    if request.method == "GET":
        return _form(actor)
    data = _form_data()
    if data["cuando"] == "programar":
        try:
            pid, primero = programados.programar(actor, data, request.form, request.files.get("imagen"),
                                                 base_url=request.url_root)
        except s.Error as error:
            flash(str(error), "error")
            return _form(actor, data, 400)
        log_audit(session, "comunicado_programar", "comunicados_programados", pid)
        flash(f"Comunicado programado. Primer envío: {primero:%d/%m/%Y a las %H:%M}.", "success")
        return redirect(url_for("comunicados.lista_programados"))
    try:
        cid, total = s.enviar(actor, data, request.files.get("imagen"))
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


@web.get("/<int:comunicado_id>/imagen")
@permission_required("comunicados", "ver")
def imagen(comunicado_id):
    version = "push" if request.args.get("version") == "push" else "app"
    return private_photo(s.imagen(who(), comunicado_id, version))


@web.get("/imagen-push/<int:comunicado_id>/<int:vence>/<firma>.jpg")
def imagen_push(comunicado_id, vence, firma):
    """Sin login: Firebase descarga la imagen de la notificacion con este link firmado y con vencimiento."""
    try:
        return private_photo(s.imagen_push(comunicado_id, vence, firma))
    except s.Error:
        abort(404)


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


@mobile.get("/<int:comunicado_id>/imagen")
@mobile_auth_required
def imagen_mobile(comunicado_id):
    """Imagen del comunicado (JPEG). No lo marca como leido."""
    return private_photo(s.imagen_empleado(employee(), comunicado_id))


@mobile.post("/<int:comunicado_id>/leido")
@mobile_auth_required
def leido(comunicado_id):
    return jsonify(s.leer(employee(), comunicado_id))


@mobile.post("/leer-todos")
@mobile_auth_required
def leer_todos():
    return jsonify(marcados=s.leer_todos(employee()))
