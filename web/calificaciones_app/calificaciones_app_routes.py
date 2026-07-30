from flask import Blueprint, render_template, request
from web.auth.decorators import role_required
from repositories.calificacion_app_repository import (
    get_calificaciones_page,
    get_estadisticas,
    get_versiones_disponibles,
)
from repositories.sector_repository import get_all as get_sectores
from repositories.sucursal_repository import get_all as get_sucursales

calificaciones_app_bp = Blueprint(
    "calificaciones_app", __name__, url_prefix="/calificaciones-app"
)

_PER_PAGE = 25


@calificaciones_app_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    page = max(1, int(request.args.get("page") or 1))
    fecha_desde = request.args.get("fecha_desde") or None
    fecha_hasta = request.args.get("fecha_hasta") or None
    version_app = request.args.get("version_app") or None
    try:
        puntuacion = int(request.args.get("puntuacion") or 0) or None
    except (ValueError, TypeError):
        puntuacion = None
    try:
        sector_id = int(request.args.get("sector_id") or 0) or None
    except (ValueError, TypeError):
        sector_id = None
    try:
        sucursal_id = int(request.args.get("sucursal_id") or 0) or None
    except (ValueError, TypeError):
        sucursal_id = None

    calificaciones, total = get_calificaciones_page(
        page,
        _PER_PAGE,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        sector_id=sector_id,
        sucursal_id=sucursal_id,
        version_app=version_app,
        puntuacion=puntuacion,
    )
    estadisticas = get_estadisticas(version_app=version_app)
    versiones = get_versiones_disponibles()
    sectores = get_sectores(include_inactive=True)
    sucursales = get_sucursales(include_inactive=True)

    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)

    return render_template(
        "calificaciones_app/listado.html",
        calificaciones=calificaciones,
        estadisticas=estadisticas,
        versiones=versiones,
        sectores=sectores,
        sucursales=sucursales,
        total=total,
        page=page,
        per_page=_PER_PAGE,
        total_pages=total_pages,
        filtros={
            "fecha_desde": fecha_desde or "",
            "fecha_hasta": fecha_hasta or "",
            "version_app": version_app or "",
            "puntuacion": puntuacion or "",
            "sector_id": sector_id or "",
            "sucursal_id": sucursal_id or "",
        },
    )
