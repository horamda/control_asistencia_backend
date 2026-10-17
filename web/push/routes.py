"""Notificaciones push: registro de dispositivos (app Android y web) y estado/prueba en el panel."""

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from routes.carga_routes import employee
from services import push_service as s
from utils.audit import log_audit
from utils.jwt_guard import mobile_auth_required
from utils.limiter import limiter
from web.auth.decorators import _cached_web_user, permission_required

web = Blueprint("push_web", __name__, url_prefix="/notificaciones-push")
mobile = Blueprint("push_mobile", __name__, url_prefix="/api/v1/mobile/push")


@mobile.errorhandler(s.Error)
def invalid(error):
    return jsonify(error=str(error)), error.status


@mobile.get("/config")
@mobile_auth_required
def config():
    """Si las notificaciones estan activas y los datos publicos para registrarse en la app web."""
    return jsonify(s.config_web())


@mobile.route("/dispositivo", methods=["POST", "DELETE"])
@mobile_auth_required
def dispositivo():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise s.Error("Envíe un objeto JSON.")
    if request.method == "DELETE":
        return jsonify(quitado=s.quitar_dispositivo(employee(), body.get("token")))
    return jsonify(s.registrar_dispositivo(employee(), body.get("token"), body.get("plataforma"), body.get("app_version")))


@mobile.post("/acuse")
@limiter.limit("120 per minute")
def acuse():
    """Sin JWT: la app confirma con data.envio_id y data.acuse del push que llego (recibido) o que tocaron
    (abierto). Tambien desde el manejador en segundo plano, donde no hay sesion."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise s.Error("Envíe un objeto JSON.")
    return jsonify(s.registrar_acuse(body.get("envio_id"), body.get("acuse"), body.get("evento")))


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


@web.get("/")
@permission_required("configuracion", "ver")
def index():
    return render_template("push/index.html", **s.estado_panel(who()))


@web.post("/prueba")
@permission_required("configuracion", "editar")
def prueba():
    try:
        resultado = s.enviar_prueba(who(), request.form.get("empleado_id", type=int) or 0)
    except s.Error as error:
        flash(str(error), "error")
        return redirect(url_for("push_web.index"))
    log_audit(session, "push_prueba", "push_envios", None)
    if resultado["enviados"]:
        flash("Notificación de prueba enviada. Debería llegar en unos segundos.", "success")
    elif resultado["sin_dispositivo"]:
        flash("Ese empleado no tiene dispositivos registrados: tiene que abrir la app y aceptar las notificaciones.", "warning")
    else:
        flash("Firebase rechazó el envío. Revisá el detalle en 'Últimos envíos'.", "error")
    return redirect(url_for("push_web.index"))
