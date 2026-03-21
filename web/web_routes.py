from flask import Blueprint, current_app, render_template, request

from repositories.empresa_repository import get_all as get_empresas
from repositories.sucursal_repository import get_all as get_sucursales
from web.auth.decorators import login_required
from web.dashboard_metrics import _dashboard_metrics, _parse_optional_int, _to_int

web_bp = Blueprint("web", __name__)


@web_bp.route("/dashboard")
@login_required
def dashboard():
    empresa_id = _parse_optional_int(request.args.get("empresa_id"))
    sucursal_id = _parse_optional_int(request.args.get("sucursal_id"))
    stats, recent_events, charts = _dashboard_metrics()
    try:
        empresas = get_empresas(include_inactive=False)
    except Exception:
        current_app.logger.warning("dashboard_get_empresas_error", exc_info=True)
        empresas = []
    try:
        sucursales = get_sucursales(include_inactive=False)
    except Exception:
        current_app.logger.warning("dashboard_get_sucursales_error", exc_info=True)
        sucursales = []

    empresa_sel = None
    sucursal_sel = None
    if empresa_id:
        empresa_sel = next((e for e in empresas if _to_int(e.get("id")) == int(empresa_id)), None)
    if sucursal_id:
        sucursal_sel = next((s for s in sucursales if _to_int(s.get("id")) == int(sucursal_id)), None)

    scope = {
        "kind": "general",
        "is_segmented": bool(empresa_id or sucursal_id),
        "label": "General (todas las empresas y sucursales)",
    }
    if sucursal_sel:
        scope["kind"] = "sucursal"
        empresa_suffix = ""
        if empresa_sel:
            empresa_suffix = f" - {empresa_sel.get('razon_social') or ''}"
        scope["label"] = f"Sucursal: {sucursal_sel.get('nombre') or ('#' + str(sucursal_id))}{empresa_suffix}"
    elif empresa_sel:
        scope["kind"] = "empresa"
        scope["label"] = f"Empresa: {empresa_sel.get('razon_social') or ('#' + str(empresa_id))}"
    elif sucursal_id:
        scope["kind"] = "sucursal"
        scope["label"] = f"Sucursal #{int(sucursal_id)}"
    elif empresa_id:
        scope["kind"] = "empresa"
        scope["label"] = f"Empresa #{int(empresa_id)}"

    stats["scope_kind"] = scope["kind"]
    stats["scope_label"] = scope["label"]

    if empresa_id:
        sucursales = [s for s in sucursales if _to_int(s.get("empresa_id")) == int(empresa_id)]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_events=recent_events,
        charts=charts,
        empresas=empresas,
        sucursales=sucursales,
        filtros={"empresa_id": empresa_id, "sucursal_id": sucursal_id},
        scope=scope,
    )
