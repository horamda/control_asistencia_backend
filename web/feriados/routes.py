"""Calendario de feriados: nacionales importados, de la empresa o de una sucursal."""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from services import feriado_service as s
from services import reunion_service
from services.carga_service import now_local
from utils.audit import log_audit
from web.auth.decorators import _cached_web_user, permission_required

feriados_bp = Blueprint("feriados", __name__, url_prefix="/feriados")


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


def _anio(raw=None):
    actual = now_local().year
    try:
        anio = int(raw or actual)
    except (TypeError, ValueError):
        return actual
    return anio if 2000 <= anio <= 2100 else actual


@feriados_bp.errorhandler(s.Error)
def invalid(error):
    flash(str(error), "error")
    return redirect(url_for("feriados.index", anio=_anio(request.values.get("anio"))))


@feriados_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@feriados_bp.get("/")
@permission_required("horarios", "ver")
def index():
    actor = who()
    anio = _anio(request.args.get("anio"))
    return render_template("feriados/index.html", feriados=s.listar(actor, anio), anio=anio,
                           sucursales=reunion_service.sucursales(actor), hoy=now_local().date())


@feriados_bp.post("/nuevo")
@permission_required("horarios", "crear")
def nuevo():
    fecha = s.guardar(who(), request.form)
    log_audit(session, "feriado_crear", "feriados", None)
    flash("Feriado agregado. Las reuniones de ese día se reprogramaron según su configuración.", "success")
    return redirect(url_for("feriados.index", anio=fecha.year))


@feriados_bp.post("/<int:feriado_id>/eliminar")
@permission_required("horarios", "eliminar")
def eliminar(feriado_id):
    row = s.eliminar(who(), feriado_id)
    log_audit(session, "feriado_eliminar", "feriados", feriado_id)
    flash(f"Feriado del {row['fecha']:%d/%m/%Y} eliminado.", "success")
    return redirect(url_for("feriados.index", anio=row["fecha"].year))


@feriados_bp.post("/importar")
@permission_required("horarios", "crear")
def importar():
    anio = _anio(request.form.get("anio"))
    resultado = s.importar_nacionales(who(), anio)
    log_audit(session, "feriados_importar", "feriados", None)
    flash(f"Feriados nacionales {anio}: {resultado['nuevos']} nuevos, {resultado['existentes']} ya estaban.", "success")
    return redirect(url_for("feriados.index", anio=anio))
