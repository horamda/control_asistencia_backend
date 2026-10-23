import calendar
import datetime as dt

from flask import Blueprint, current_app, render_template, request, session

from repositories.asistencia_dia_no_laborable_repository import get_dates as get_dias_no_laborables
from repositories.empresa_repository import get_all as get_empresas
from repositories.sucursal_repository import get_all as get_sucursales
from services import inicio_service
from web.auth.decorators import _cached_web_user, can_access_module, has_role, login_required, permission_required
from services.svg_chart_service import column_chart, line_chart
from web.dashboard_metrics import _dashboard_metrics, _dashboard_trends, _parse_optional_int, _to_int

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


def _empresa_forzada():
    """Empresa a la que queda limitado un usuario que no es admin (None para admin: ve todas). Sin empresa asignada
    devuelve 0, que no coincide con ninguna: no ve datos de otras."""
    user = _cached_web_user(session.get("user_id")) or {}
    if str(user.get("rol") or "").strip().lower() == "admin":
        return None
    return _to_int(user.get("empresa_id")) or 0


def _filtros_de_alcance():
    """empresa_id y sucursal_id pedidos, con la empresa fija para quien no es admin."""
    forzada = _empresa_forzada()
    empresa_id = forzada if forzada is not None else _parse_optional_int(request.args.get("empresa_id"))
    return forzada, empresa_id, _parse_optional_int(request.args.get("sucursal_id"))


def _empresas_y_sucursales(forzada=None):
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
    if forzada is not None:
        empresas = [e for e in empresas if _to_int(e.get("id")) == forzada]
        sucursales = [x for x in sucursales if _to_int(x.get("empresa_id")) == forzada]
    return empresas, sucursales


@web_bp.route("/dashboard")
@login_required
def dashboard():
    """Inicio del panel: lo de hoy, lo que hay que resolver y el mes, segun los permisos del usuario. Las estadisticas
    completas estan en /estadisticas-asistencia."""
    user_id = session.get("user_id")
    permisos = {}

    def puede(modulo):
        if modulo not in permisos:
            try:
                permisos[modulo] = bool(can_access_module(user_id, modulo, "ver"))
            except Exception:
                current_app.logger.warning("inicio_permiso_error", exc_info=True)
                permisos[modulo] = False
        return permisos[modulo]

    forzada, empresa_id, sucursal_id = _filtros_de_alcance()
    empresas, sucursales = _empresas_y_sucursales(forzada) if puede("asistencias") else ([], [])
    try:
        datos = inicio_service.resumen(puede=puede, empresa_id=empresa_id, sucursal_id=sucursal_id)
    except Exception:
        current_app.logger.exception("inicio_error")
        datos = {"asistencia": None, "pendientes": []}
    presencia = None
    # Sin empresa asignada (0) no se consulta: la presencia sin empresa son todas.
    if puede("asistencias") and forzada != 0:
        try:
            presencia = inicio_service.presencia(empresa_id=empresa_id, sucursal_id=sucursal_id)
        except Exception:
            current_app.logger.warning("inicio_presencia_error", exc_info=True)
    if empresa_id:
        sucursales = [s for s in sucursales if _to_int(s.get("empresa_id")) == int(empresa_id)]
    return render_template(
        "inicio.html",
        presencia=presencia,
        asistencia=datos["asistencia"],
        pendientes=datos["pendientes"],
        pendientes_total=sum(p["cantidad"] for p in datos["pendientes"]),
        ve_asistencia=puede("asistencias"),
        empresas=empresas,
        sucursales=sucursales,
        filtros={"empresa_id": empresa_id, "sucursal_id": sucursal_id},
        empresa_fija=forzada is not None,
        hoy=dt.date.today(),
    )


@web_bp.route("/estadisticas-asistencia")
@permission_required("asistencias", "ver")
def estadisticas_asistencia():
    """Estadisticas completas de asistencia (lo que antes estaba en el inicio): rankings, comparativas, horas, riesgo."""
    forzada, empresa_id, sucursal_id = _filtros_de_alcance()
    stats, recent_events, charts = _dashboard_metrics(empresa_forzada=forzada)
    empresas, sucursales = _empresas_y_sucursales(forzada)

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
        "estadisticas_asistencia.html",
        stats=stats,
        recent_events=recent_events,
        charts=charts,
        empresas=empresas,
        sucursales=sucursales,
        filtros={"empresa_id": empresa_id, "sucursal_id": sucursal_id},
        scope=scope,
        labor_calendar=labor_calendar,
        empresa_fija=forzada is not None,
    )


EVOLUCION_PERIODOS = (6, 12)


def _num(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _pct_text(value) -> str:
    return "s/d" if value is None else f"{value:.1f}%"


def _evolucion_textos(meses: list[dict], dias_semana: list[dict]) -> tuple[dict, dict]:
    """Tooltips (por punto) y filas de las tablas equivalentes de cada grafico."""
    tooltips = {"ausentismo": [], "puntualidad": [], "semana": []}
    tablas = {"ausentismo": [], "puntualidad": [], "semana": []}
    for m in meses:
        titulo = m["nombre"] + (" (parcial)" if m["parcial"] else "")
        aus, just = _pct_text(m["ausentismo_pct"]), _pct_text(m["justificadas_pct"])
        tooltips["ausentismo"].append({
            "title": titulo,
            "rows": [
                {"key": "ausentismo", "name": "Faltas injustificadas", "value": aus},
                {"key": "justificadas", "name": "Ausencias justificadas", "value": just},
            ],
            "note": f"{_num(m['ausencias'])} faltas y {_num(m['justificadas'])} justificadas en {_num(m['dias_posibles'])} días posibles",
            "aria": f"{titulo}: faltas injustificadas {aus}, ausencias justificadas {just}",
        })
        tablas["ausentismo"].append([titulo, aus, just, _num(m["dias_posibles"])])
        punt = _pct_text(m["puntualidad_pct"])
        tooltips["puntualidad"].append({
            "title": titulo,
            "rows": [{"key": "puntualidad", "name": "Puntualidad", "value": punt}],
            "note": f"{_num(m['en_horario'])} en horario de {_num(m['fichadas'])} fichadas",
            "aria": f"{titulo}: puntualidad {punt}",
        })
        tablas["puntualidad"].append([titulo, punt, _num(m["en_horario"]), _num(m["fichadas"])])
    for d in dias_semana:
        tasa = _pct_text(d["value"])
        tooltips["semana"].append({
            "title": d["nombre"],
            "rows": [{"key": "semana", "name": "Faltas injustificadas", "value": tasa}],
            "note": f"{_num(d['ausencias'])} faltas en {_num(d['posibles'])} días posibles",
            "aria": f"{d['nombre']}: {tasa} de faltas injustificadas",
        })
        tablas["semana"].append([d["nombre"], tasa, _num(d["ausencias"]), _num(d["posibles"])])
    return tooltips, tablas


@web_bp.route("/dashboard/evolucion")
@permission_required("asistencias", "ver")
def dashboard_evolucion():
    """Fragmento del dashboard (cargado con htmx): evolucion mensual."""
    meses = request.args.get("meses", 12, type=int)
    if meses not in EVOLUCION_PERIODOS:
        meses = 12
    _, empresa_id, sucursal_id = _filtros_de_alcance()
    filtros = {"empresa_id": empresa_id, "sucursal_id": sucursal_id}
    graficos = None
    try:
        trends = _dashboard_trends(months=meses, **filtros)
        labels = [{"label": m["label"], "sub": m["sub"]} for m in trends["meses"]]
        graficos = {
            "meses": trends["meses"],
            "dias_semana": trends["dias_semana"],
            "ausentismo": line_chart(labels, [
                {"key": "ausentismo", "name": "Faltas injustificadas",
                 "values": [m["ausentismo_pct"] for m in trends["meses"]]},
                {"key": "justificadas", "name": "Ausencias justificadas",
                 "values": [m["justificadas_pct"] for m in trends["meses"]]},
            ], width=880, height=260),
            "puntualidad": line_chart(labels, [
                {"key": "puntualidad", "name": "Puntualidad",
                 "values": [m["puntualidad_pct"] for m in trends["meses"]]},
            ], y_min=None, y_max=100),
            "semana": column_chart(trends["dias_semana"]),
        }
        graficos["tooltips"], graficos["tablas"] = _evolucion_textos(trends["meses"], trends["dias_semana"])
    except Exception:
        current_app.logger.exception("dashboard_evolucion_error")
    return render_template(
        "_dashboard_evolucion.html",
        graficos=graficos,
        meses=meses,
        periodos=EVOLUCION_PERIODOS,
        filtros=filtros,
    )
