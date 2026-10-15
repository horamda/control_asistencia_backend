from flask import Blueprint, current_app, render_template, request

from services.performance_report_service import PERIODOS, build_report
from web.auth.decorators import strict_admin_required

rendimiento_bp = Blueprint("rendimiento", __name__, url_prefix="/rendimiento")


@rendimiento_bp.route("/")
@strict_admin_required
def reporte():
    periodo = request.args.get("periodo", "24h")
    if periodo not in PERIODOS:
        periodo = "24h"
    try:
        reporte_data = build_report(periodo)
    except Exception:
        # Por ejemplo, la tabla todavia no existe porque no corrio la migracion.
        current_app.logger.exception("rendimiento_reporte_error")
        reporte_data = None
    return render_template("rendimiento/reporte.html", r=reporte_data, periodo=periodo, periodos=PERIODOS)
