import calendar
import datetime as dt

from flask import Blueprint, current_app, render_template, request, session

from repositories.asistencia_dia_no_laborable_repository import get_dates as get_dias_no_laborables
from repositories.empresa_repository import get_all as get_empresas
from repositories.sucursal_repository import get_all as get_sucursales
from web.auth.decorators import has_role, login_required
from web.dashboard_metrics import _dashboard_metrics, _parse_optional_int, _to_int

web_bp = Blueprint("web", __name__)


def _dashboard_labor_calendar(*, empresa_id: int | None, sucursal_id: int | None) -> dict:
    today = dt.date.today()
    first = dt.date(today.year, today.month, 1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_dates = [dt.date(today.year, today.month, day) for day in range(1, last_day + 1)]
    try:
        non_laborable_days = get_dias_no_laborables(
            year=today.year,
            month=today.month,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
        )
    except Exception:
        current_app.logger.warning("dashboard_get_dias_no_laborables_error", exc_info=True)
        non_laborable_days = set()
    non_laborable_days = set(non_laborable_days)
    for day in month_dates:
        if day.weekday() == 6:
            non_laborable_days.add(day.isoformat())

    month_names = [
        "",
        "Enero",
        "Febrero",
        "Marzo",
        "Abril",
        "Mayo",
        "Junio",
        "Julio",
        "Agosto",
        "Septiembre",
        "Octubre",
        "Noviembre",
        "Diciembre",
    ]
    user_id = session.get("user_id")
    can_edit = False
    if user_id:
        try:
            can_edit = has_role(user_id, "admin")
        except Exception:
            current_app.logger.warning("dashboard_labor_calendar_role_error", exc_info=True)

    return {
        "mes": f"{today.year:04d}-{today.month:02d}",
        "label": f"{month_names[today.month]} {today.year}",
        "month_dates": month_dates,
        "first_weekday": first.isoweekday() % 7,
        "non_laborable_days": non_laborable_days,
        "non_laborable_count": len(non_laborable_days),
        "can_edit": can_edit,
    }


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
    labor_calendar = _dashboard_labor_calendar(empresa_id=empresa_id, sucursal_id=sucursal_id)

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_events=recent_events,
        charts=charts,
        empresas=empresas,
        sucursales=sucursales,
        filtros={"empresa_id": empresa_id, "sucursal_id": sucursal_id},
        scope=scope,
        labor_calendar=labor_calendar,
    )
