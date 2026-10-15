from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from repositories.configuracion_empresa_repository import get_all as get_configuraciones
from services import egreso_automatico_service as svc
from utils.audit import log_audit
from utils.forms import parse_date as _parse_date
from web.auth.decorators import role_required

egresos_automaticos_bp = Blueprint("egresos_automaticos", __name__, url_prefix="/asistencias/egresos-automaticos")


def _fecha(raw):
    try:
        return _parse_date(raw)
    except ValueError:
        return None


def _contexto(simulacion=None):
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = 20
    desde = _fecha(request.args.get("desde"))
    hasta = _fecha(request.args.get("hasta"))
    q = (request.args.get("q") or "").strip() or None
    cerradas, total = svc.cerradas_page(page=page, per_page=per_page, desde=desde, hasta=hasta, q=q)
    return dict(
        pendientes=svc.pendientes(),
        ejecuciones=svc.ejecuciones(),
        configuraciones=get_configuraciones(),
        cerradas=cerradas,
        total=total,
        page=page,
        per_page=per_page,
        filtros={"desde": desde or "", "hasta": hasta or "", "q": q or ""},
        simulacion=simulacion,
    )


@egresos_automaticos_bp.route("/")
@role_required("admin", "rrhh")
def index():
    return render_template("asistencias/egresos_automaticos.html", **_contexto())


@egresos_automaticos_bp.route("/simular", methods=["POST"])
@role_required("admin", "rrhh")
def simular():
    resumen = svc.cerrar_jornadas_abiertas(dry_run=True)
    return render_template("asistencias/egresos_automaticos.html", **_contexto(simulacion=resumen))


@egresos_automaticos_bp.route("/ejecutar", methods=["POST"])
@role_required("admin", "rrhh")
def ejecutar():
    try:
        resumen = svc.cerrar_jornadas_abiertas(origen="manual", usuario_id=session.get("user_id"))
    except Exception:
        current_app.logger.exception("egresos_automaticos_ejecutar_error")
        flash("No se pudo ejecutar el cierre. Revise los logs e intente nuevamente.", "error")
        return redirect(url_for("egresos_automaticos.index"))
    log_audit(session, "egreso_automatico_manual", "asistencias", None)
    mensaje = f"Se cerraron {resumen['cerradas']} jornada(s) sin egreso"
    if resumen["errores"]:
        mensaje += f"; {resumen['errores']} con error (ver logs)"
    flash(mensaje + ".", "error" if resumen["errores"] else "success")
    return redirect(url_for("egresos_automaticos.index"))


@egresos_automaticos_bp.route("/recalcular", methods=["POST"])
@role_required("admin", "rrhh")
def recalcular():
    """Aplica las horas configuradas actuales a las jornadas ya cerradas por parametro."""
    try:
        resumen = svc.recalcular_por_parametro()
    except Exception:
        current_app.logger.exception("egresos_automaticos_recalcular_error")
        flash("No se pudo recalcular. Revise los logs e intente nuevamente.", "error")
        return redirect(url_for("egresos_automaticos.index"))
    log_audit(session, "egreso_automatico_recalculo", "asistencias", None)
    if resumen["cambiadas"]:
        flash(f"Se recalcularon {resumen['cambiadas']} jornada(s) con las horas configuradas actuales.", "success")
    else:
        flash("Todas las jornadas cerradas por horas configuradas ya usan el valor actual.", "success")
    return redirect(url_for("egresos_automaticos.index"))
