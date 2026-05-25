from flask import Blueprint, render_template, request
from web.auth.decorators import role_required
from repositories.mobile_sesiones_repository import (
    get_sesiones_page,
    get_stats,
    get_versiones_disponibles,
)

mobile_stats_bp = Blueprint("mobile_stats", __name__, url_prefix="/mobile-stats")

_PER_PAGE = 30


@mobile_stats_bp.route("/")
@role_required("admin")
def listado():
    page = max(1, int(request.args.get("page") or 1))
    fecha_desde = request.args.get("fecha_desde") or None
    fecha_hasta = request.args.get("fecha_hasta") or None
    platform = request.args.get("platform") or None
    app_version = request.args.get("app_version") or None
    empleado_q = request.args.get("q") or None

    sesiones, total = get_sesiones_page(
        page,
        _PER_PAGE,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        platform=platform,
        app_version=app_version,
        empleado_q=empleado_q,
    )
    stats = get_stats()
    versiones = get_versiones_disponibles()
    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)

    return render_template(
        "mobile_stats/listado.html",
        sesiones=sesiones,
        stats=stats,
        versiones=versiones,
        total=total,
        page=page,
        per_page=_PER_PAGE,
        total_pages=total_pages,
        filtros={
            "fecha_desde": fecha_desde or "",
            "fecha_hasta": fecha_hasta or "",
            "platform": platform or "",
            "app_version": app_version or "",
            "q": empleado_q or "",
        },
    )
