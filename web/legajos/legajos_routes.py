import csv
import datetime
import io
from collections import defaultdict

from flask import Blueprint, Response, abort, redirect, render_template, request, session, url_for

from utils.forms import parse_date as _parse_date, parse_int as _parse_int, safe_next_url as _safe_next_url
from repositories.empleado_repository import get_all as get_empleados
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.empleado_repository import get_page as _get_empleados_page
from repositories.asistencia_repository import get_page as _get_asistencias_page
from repositories.justificacion_repository import get_page as _get_justificaciones_page
from repositories.vacacion_repository import get_page_by_empleado as _get_vacaciones_page
from repositories.empresa_repository import get_all as get_empresas
from repositories.legajo_adjunto_repository import (
    create_adjunto,
    get_adjunto_by_id,
    get_adjuntos_by_evento,
    mark_deleted,
)
from repositories.legajo_evento_repository import (
    anular_evento,
    create_evento,
    get_evento_by_id,
    get_eventos_page,
    get_eventos_by_empleado,
    get_tipo_evento_by_id,
    get_tipos_evento,
    update_evento,
)
from repositories.empleado_horario_repository import get_actual_by_empleado as _get_horario_actual
from services.horario_service import get_horario_estructurado as _get_horario_estructurado
from services.legajo_attachment_service import save_legajo_attachment_local
from utils.audit import log_audit
from web.auth.decorators import role_required

legajos_bp = Blueprint("legajos", __name__, url_prefix="/legajos")



def _extract_evento_form(form):
    return {
        "tipo_id": _parse_int(form.get("tipo_id")),
        "fecha_evento": (form.get("fecha_evento") or "").strip(),
        "fecha_desde": (form.get("fecha_desde") or "").strip(),
        "fecha_hasta": (form.get("fecha_hasta") or "").strip(),
        "titulo": (form.get("titulo") or "").strip(),
        "descripcion": (form.get("descripcion") or "").strip(),
        "severidad": (form.get("severidad") or "").strip() or None,
        "justificacion_id": _parse_int(form.get("justificacion_id")),
    }


def _date_to_input_value(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _evento_to_form_data(evento: dict):
    return {
        "tipo_id": evento.get("tipo_id"),
        "fecha_evento": _date_to_input_value(evento.get("fecha_evento")),
        "fecha_desde": _date_to_input_value(evento.get("fecha_desde")),
        "fecha_hasta": _date_to_input_value(evento.get("fecha_hasta")),
        "titulo": evento.get("titulo") or "",
        "descripcion": evento.get("descripcion") or "",
        "severidad": evento.get("severidad") or "",
        "justificacion_id": evento.get("justificacion_id"),
    }


def _validate_evento_data(data: dict, tipo: dict | None):
    errors = []
    if not data.get("tipo_id"):
        errors.append("Tipo de evento es requerido.")
    if not tipo or not tipo.get("activo"):
        errors.append("Tipo de evento invalido.")

    try:
        data["fecha_evento"] = _parse_date(data.get("fecha_evento"))
    except ValueError:
        errors.append("Fecha de evento invalida.")

    try:
        data["fecha_desde"] = _parse_date(data.get("fecha_desde"))
    except ValueError:
        errors.append("Fecha desde invalida.")

    try:
        data["fecha_hasta"] = _parse_date(data.get("fecha_hasta"))
    except ValueError:
        errors.append("Fecha hasta invalida.")

    if not data.get("descripcion"):
        errors.append("Descripcion es requerida.")

    if data.get("severidad") and data["severidad"] not in {"leve", "media", "grave"}:
        errors.append("Severidad invalida.")

    if data.get("fecha_desde") and data.get("fecha_hasta"):
        if data["fecha_hasta"] < data["fecha_desde"]:
            errors.append("Fecha hasta debe ser mayor o igual a fecha desde.")

    if tipo and tipo.get("requiere_rango_fechas"):
        if not data.get("fecha_desde") or not data.get("fecha_hasta"):
            errors.append("Este tipo requiere fecha desde y fecha hasta.")

    return errors


def _build_evento_payload(data: dict, *, empresa_id: int, empleado_id: int, actor_id: int | None):
    return {
        "empresa_id": empresa_id,
        "empleado_id": empleado_id,
        "tipo_id": data.get("tipo_id"),
        "fecha_evento": data.get("fecha_evento"),
        "fecha_desde": data.get("fecha_desde"),
        "fecha_hasta": data.get("fecha_hasta"),
        "titulo": data.get("titulo") or None,
        "descripcion": data.get("descripcion"),
        "severidad": data.get("severidad"),
        "justificacion_id": data.get("justificacion_id"),
        "created_by_usuario_id": actor_id,
        "updated_by_usuario_id": actor_id,
    }


def _load_empleado_context(emp_id: int):
    empleado = get_empleado_by_id(emp_id)
    if not empleado:
        abort(404)
    eventos = get_eventos_by_empleado(emp_id, include_anulados=True)
    tipos = get_tipos_evento(include_inactive=False)
    adjuntos_by_evento = {}
    for evento in eventos:
        evento_id = int(evento["id"])
        adjuntos_by_evento[evento_id] = get_adjuntos_by_evento(evento_id, include_deleted=False)
    return empleado, eventos, tipos, adjuntos_by_evento


def _save_adjuntos(archivos, *, empresa_id: int, empleado_id: int, evento_id: int, actor_id):
    for file_storage in archivos:
        if not file_storage or not str(file_storage.filename or "").strip():
            continue
        saved = save_legajo_attachment_local(
            file_storage,
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            evento_id=evento_id,
        )
        adjunto_id = create_adjunto(
            {
                "evento_id": evento_id,
                "empresa_id": empresa_id,
                "empleado_id": empleado_id,
                "nombre_original": saved["nombre_original"],
                "mime_type": saved["mime_type"],
                "extension": saved["extension"],
                "tamano_bytes": saved["tamano_bytes"],
                "sha256": saved["sha256"],
                "storage_backend": saved["storage_backend"],
                "storage_ruta": saved["storage_ruta"],
                "storage_data": saved.get("storage_data"),
                "created_by_usuario_id": actor_id,
            }
        )
        log_audit(session, "create", "legajo_evento_adjuntos", adjunto_id)


@legajos_bp.route("/")
@role_required("admin", "rrhh", "supervisor")
def listado_empleados():
    empleados = get_empleados(include_inactive=True)
    return render_template("legajos/listado.html", empleados=empleados)


@legajos_bp.route("/eventos/")
@role_required("admin", "rrhh", "supervisor")
def listado_eventos():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    if per_page not in {10, 20, 50, 100}:
        per_page = 20

    search = str(request.args.get("q") or "").strip() or None
    empresa_id = request.args.get("empresa_id", type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    tipo_id = request.args.get("tipo_id", type=int)

    estado_raw = str(request.args.get("estado") or "all").strip().lower()
    if estado_raw not in {"all", "vigente", "anulado"}:
        estado_raw = "all"
    estado = None if estado_raw == "all" else estado_raw

    eventos, total = get_eventos_page(
        page=page,
        per_page=per_page,
        search=search,
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        tipo_id=tipo_id,
        estado=estado,
    )
    empresas = get_empresas(include_inactive=True)
    empleados = get_empleados(include_inactive=True)
    tipos = get_tipos_evento(include_inactive=True)

    return render_template(
        "legajos/eventos_listado.html",
        eventos=eventos,
        total=total,
        page=page,
        per_page=per_page,
        q=search,
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        tipo_id=tipo_id,
        estado=estado_raw,
        empresas=empresas,
        empleados=empleados,
        tipos=tipos,
    )


@legajos_bp.route("/empleado/<int:emp_id>")
@role_required("admin", "rrhh", "supervisor")
def empleado(emp_id):
    empleado_data, eventos, tipos, adjuntos_by_evento = _load_empleado_context(emp_id)
    return render_template(
        "legajos/empleado.html",
        empleado=empleado_data,
        eventos=eventos,
        tipos=tipos,
        adjuntos_by_evento=adjuntos_by_evento,
        errors=[],
        form_data={},
    )


@legajos_bp.route("/empleado/<int:emp_id>/eventos", methods=["POST"])
@role_required("admin", "rrhh")
def crear_evento(emp_id):
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)

    data = _extract_evento_form(request.form)
    tipo = get_tipo_evento_by_id(data.get("tipo_id")) if data.get("tipo_id") else None
    errors = _validate_evento_data(data, tipo)

    if errors:
        _, eventos, tipos, adjuntos_by_evento = _load_empleado_context(emp_id)
        return render_template(
            "legajos/empleado.html",
            empleado=empleado_data,
            eventos=eventos,
            tipos=tipos,
            adjuntos_by_evento=adjuntos_by_evento,
            errors=errors,
            form_data=data,
        )

    actor_id = session.get("user_id")
    payload = _build_evento_payload(
        data,
        empresa_id=int(empleado_data["empresa_id"]),
        empleado_id=int(emp_id),
        actor_id=actor_id,
    )
    payload["estado"] = "vigente"
    evento_id = create_evento(payload)
    log_audit(session, "create", "legajo_eventos", evento_id)

    _save_adjuntos(
        request.files.getlist("adjuntos"),
        empresa_id=int(empleado_data["empresa_id"]),
        empleado_id=int(emp_id),
        evento_id=int(evento_id),
        actor_id=actor_id,
    )

    return redirect(url_for("legajos.empleado", emp_id=emp_id))


@legajos_bp.route("/empleado/<int:emp_id>/eventos/<int:evento_id>/editar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar_evento(emp_id, evento_id):
    next_url = _safe_next_url(request.values.get("next"))
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)
    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)
    if str(evento.get("estado") or "").lower() == "anulado":
        abort(400, description="No se puede editar un evento anulado.")

    tipos = get_tipos_evento(include_inactive=False)
    errors = []
    form_data = _evento_to_form_data(evento)

    if request.method == "POST":
        form_data = _extract_evento_form(request.form)
        tipo = get_tipo_evento_by_id(form_data.get("tipo_id")) if form_data.get("tipo_id") else None
        errors = _validate_evento_data(form_data, tipo)
        if not errors:
            actor_id = session.get("user_id")
            payload = _build_evento_payload(
                form_data,
                empresa_id=int(empleado_data["empresa_id"]),
                empleado_id=int(emp_id),
                actor_id=actor_id,
            )
            update_evento(evento_id, payload)
            log_audit(session, "update", "legajo_eventos", evento_id)
            return redirect(next_url or url_for("legajos.empleado", emp_id=emp_id))

    return render_template(
        "legajos/evento_form.html",
        mode="edit",
        empleado=empleado_data,
        evento=evento,
        tipos=tipos,
        errors=errors,
        form_data=form_data,
        next_url=next_url,
    )


@legajos_bp.route("/empleado/<int:emp_id>/eventos/<int:evento_id>/anular", methods=["POST"])
@role_required("admin", "rrhh")
def anular_evento_route(emp_id, evento_id):
    next_url = _safe_next_url(request.values.get("next"))
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)
    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)

    motivo = (request.form.get("motivo_anulacion") or "").strip() or None
    actor_id = session.get("user_id")
    anular_evento(evento_id, actor_id, motivo)
    log_audit(session, "anular", "legajo_eventos", evento_id)
    return redirect(next_url or url_for("legajos.empleado", emp_id=emp_id))


@legajos_bp.route("/empleado/<int:emp_id>/eventos/<int:evento_id>/adjuntos", methods=["POST"])
@role_required("admin", "rrhh")
def agregar_adjuntos(emp_id, evento_id):
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)
    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)
    if str(evento.get("estado") or "").lower() == "anulado":
        abort(400, description="No se pueden adjuntar archivos a un evento anulado.")

    actor_id = session.get("user_id")
    _save_adjuntos(
        request.files.getlist("adjuntos"),
        empresa_id=int(empleado_data["empresa_id"]),
        empleado_id=int(emp_id),
        evento_id=int(evento_id),
        actor_id=actor_id,
    )

    return redirect(url_for("legajos.empleado", emp_id=emp_id))


@legajos_bp.route(
    "/empleado/<int:emp_id>/eventos/<int:evento_id>/adjuntos/<int:adjunto_id>/eliminar",
    methods=["POST"],
)
@role_required("admin", "rrhh")
def eliminar_adjunto(emp_id, evento_id, adjunto_id):
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)

    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)
    if str(evento.get("estado") or "").lower() == "anulado":
        abort(400, description="No se pueden eliminar adjuntos de un evento anulado.")

    adjunto = get_adjunto_by_id(adjunto_id)
    if not adjunto or int(adjunto["evento_id"]) != int(evento_id):
        abort(404)
    if str(adjunto.get("estado") or "").lower() != "activo":
        return redirect(url_for("legajos.empleado", emp_id=emp_id))

    actor_id = session.get("user_id")
    mark_deleted(adjunto_id, actor_id)
    log_audit(session, "delete", "legajo_evento_adjuntos", adjunto_id)
    return redirect(url_for("legajos.empleado", emp_id=emp_id))


# ---------------------------------------------------------------------------
# Dashboard por empleado — helpers
# ---------------------------------------------------------------------------

def _resolve_period(periodo, desde_raw, hasta_raw):
    today = datetime.date.today()
    if periodo == "7d":
        return (today - datetime.timedelta(days=6)).isoformat(), today.isoformat(), "7d"
    if periodo == "30d":
        return (today - datetime.timedelta(days=29)).isoformat(), today.isoformat(), "30d"
    if periodo == "90d":
        return (today - datetime.timedelta(days=89)).isoformat(), today.isoformat(), "90d"
    if periodo == "mes_actual":
        return today.replace(day=1).isoformat(), today.isoformat(), "mes_actual"
    if periodo == "anio_actual":
        return today.replace(month=1, day=1).isoformat(), today.isoformat(), "anio_actual"
    # custom
    try:
        desde = datetime.date.fromisoformat(desde_raw) if desde_raw else today - datetime.timedelta(days=29)
    except ValueError:
        desde = today - datetime.timedelta(days=29)
    try:
        hasta = datetime.date.fromisoformat(hasta_raw) if hasta_raw else today
    except ValueError:
        hasta = today
    if hasta < desde:
        hasta = desde
    return desde.isoformat(), hasta.isoformat(), "custom"


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.date):
        return value
    if hasattr(value, "date"):
        return value.date()
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _td_to_hours(value):
    """Convert a MySQL TIME (timedelta) or HH:MM:SS string to float hours."""
    if value is None:
        return None
    if isinstance(value, datetime.timedelta):
        secs = value.total_seconds()
        return secs / 3600 if secs >= 0 else None
    if isinstance(value, str):
        parts = value.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
            return h + m / 60 + s / 3600
        except (ValueError, IndexError):
            return None
    return None


def _count_workdays(desde_str, hasta_str):
    """Count Mon-Fri days in [desde, hasta] inclusive."""
    try:
        d = datetime.date.fromisoformat(str(desde_str)[:10])
        end = datetime.date.fromisoformat(str(hasta_str)[:10])
    except (ValueError, TypeError):
        return 0
    count = 0
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += datetime.timedelta(days=1)
    return count


_ESTADO_LABEL = {
    "ok": "OK / Puntual",
    "tarde": "Tardanza",
    "ausente": "Ausente",
    "salida_anticipada": "Salida anticipada",
    "none": "Sin registro",
}

_WEEKDAY_NAMES = ["L", "M", "X", "J", "V", "S", "D"]
_MONTH_NAMES = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
_MONTH_NAMES_FULL = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                     "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _build_calendar_months(daily_map, desde, hasta):
    """
    Construye una lista de meses con grilla lun–dom.
    Todos los días del rango son válidos: tienen data o aparecen como nodata/weekend.
    Retorna lista de dicts:
      { key, name, month_num, year, weeks: [[day|None, ...], ...] }
    """
    try:
        d_start = datetime.date.fromisoformat(str(desde)[:10])
        d_end = datetime.date.fromisoformat(str(hasta)[:10])
    except (ValueError, TypeError):
        return []

    if (d_end - d_start).days > 400:
        d_start = d_end - datetime.timedelta(days=400)

    months = []
    cur = d_start.replace(day=1)

    while cur <= d_end:
        year, month = cur.year, cur.month
        if month == 12:
            month_end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            month_end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

        days = []
        d = cur
        while d <= month_end:
            ds = d.isoformat()
            dm = daily_map.get(ds)
            is_weekend = d.weekday() >= 5

            if dm:
                estado = dm["estado"]
                parts = [ds, _ESTADO_LABEL.get(estado, estado)]
                if dm.get("horas"):
                    parts.append(f"{dm['horas']}h")
                if dm.get("tardes"):
                    parts.append(f"{dm['tardes']} tardanza(s)")
                if dm.get("ausentes"):
                    parts.append(f"{dm['ausentes']} ausencia(s)")
                tooltip = " · ".join(parts)
            else:
                estado = "weekend" if is_weekend else "nodata"
                tooltip = f"{ds} — {'Fin de semana' if is_weekend else 'Sin registro'}"

            days.append({
                "date": ds,
                "num": d.day,
                "weekday": d.weekday(),
                "is_weekend": is_weekend,
                "estado": estado,
                "horas": (dm or {}).get("horas"),
                "tooltip": tooltip,
            })
            d += datetime.timedelta(days=1)

        weeks = []
        week = [None] * days[0]["weekday"]
        for day in days:
            week.append(day)
            if len(week) == 7:
                weeks.append(week)
                week = []
        if week:
            week += [None] * (7 - len(week))
            weeks.append(week)

        months.append({
            "key": f"{year}-{month:02d}",
            "name": f"{_MONTH_NAMES_FULL[month]} {year}",
            "month_num": month,
            "year": year,
            "weeks": weeks,
        })

        if month == 12:
            cur = datetime.date(year + 1, 1, 1)
        else:
            cur = datetime.date(year, month + 1, 1)

    return months


def _build_calendar_grid(daily_map, desde, hasta):
    """
    Returns (calendar_weeks, semanas_rows).

    calendar_weeks: list of week-rows, each a list of 7 day-dicts (or None for padding).
    Each day-dict: {date, num, mes, is_weekend, estado, horas, registros, tardes, ausentes, salidas, tooltip}

    semanas_rows: list of per-week summary dicts.
    """
    try:
        d_start = datetime.date.fromisoformat(str(desde)[:10])
        d_end = datetime.date.fromisoformat(str(hasta)[:10])
    except (ValueError, TypeError):
        return [], []

    if (d_end - d_start).days > 366:
        d_start = d_end - datetime.timedelta(days=365)

    # Build day objects in order
    days = []
    d = d_start
    while d <= d_end:
        ds = d.isoformat()
        dm = daily_map.get(ds)
        is_weekend = d.weekday() >= 5

        if dm:
            estado = dm["estado"]
            tooltip_parts = [ds, _ESTADO_LABEL.get(estado, estado)]
            if dm.get("horas"):
                tooltip_parts.append(f"{dm['horas']}h trabajadas")
            if dm["tardes"]:
                tooltip_parts.append(f"{dm['tardes']} tardanza(s)")
            if dm["ausentes"]:
                tooltip_parts.append(f"{dm['ausentes']} ausencia(s)")
            tooltip = " · ".join(tooltip_parts)
        else:
            estado = "weekend" if is_weekend else "nodata"
            tooltip = f"{ds} — {'Fin de semana' if is_weekend else 'Sin registro'}"

        days.append({
            "date": ds,
            "num": d.day,
            "mes": _MONTH_NAMES[d.month],
            "mes_num": d.month,
            "weekday": d.weekday(),
            "is_weekend": is_weekend,
            "estado": estado,
            "horas": (dm or {}).get("horas"),
            "registros": (dm or {}).get("registros", 0),
            "tardes": (dm or {}).get("tardes", 0),
            "ausentes": (dm or {}).get("ausentes", 0),
            "salidas": (dm or {}).get("salidas", 0),
            "tooltip": tooltip,
        })
        d += datetime.timedelta(days=1)

    # Group into weeks (rows of 7, Mon=0 ... Sun=6), padding start/end
    weeks = []
    current_week = [None] * days[0]["weekday"]
    for day in days:
        current_week.append(day)
        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []
    if current_week:
        current_week += [None] * (7 - len(current_week))
        weeks.append(current_week)

    # Weekly summary rows
    week_map = {}
    for day in days:
        if day["is_weekend"]:
            continue
        iso = datetime.date.fromisoformat(day["date"]).isocalendar()
        wkey = f"{iso[0]}-W{iso[1]:02d}"
        if wkey not in week_map:
            week_map[wkey] = {
                "label": f"Sem {iso[1]}",
                "desde": day["date"],
                "hasta": day["date"],
                "registros": 0, "ok": 0, "tardes": 0, "ausentes": 0, "salidas": 0,
            }
        ws = week_map[wkey]
        ws["registros"] += day["registros"]
        ws["ok"] += (day["registros"] - day["tardes"] - day["ausentes"] - day["salidas"])
        ws["tardes"] += day["tardes"]
        ws["ausentes"] += day["ausentes"]
        ws["salidas"] += day["salidas"]
        if day["date"] > ws["hasta"]:
            ws["hasta"] = day["date"]

    semanas_rows = sorted(week_map.values(), key=lambda x: x["desde"])

    return weeks, semanas_rows


def _rows_to_daily_map(rows: list) -> dict:
    """Convierte una lista de filas de asistencia en un daily_map {fecha: {...}}."""
    daily_map: dict = {}
    _rank = {"ausente": 4, "salida_anticipada": 3, "tarde": 2, "ok": 1}
    for r in rows:
        fecha = r.get("fecha")
        if not fecha:
            continue
        ds = str(fecha)[:10]
        if ds not in daily_map:
            daily_map[ds] = {
                "registros": 0, "tardes": 0, "ausentes": 0,
                "salidas": 0, "ok": 0, "estado": "none", "horas": None,
            }
        dm = daily_map[ds]
        dm["registros"] += 1
        estado = str(r.get("estado") or "").lower()
        if estado == "tarde":
            dm["tardes"] += 1
        elif estado == "ausente":
            dm["ausentes"] += 1
        elif estado == "salida_anticipada":
            dm["salidas"] += 1
        elif estado == "ok":
            dm["ok"] += 1
        if _rank.get(estado, 0) > _rank.get(dm["estado"], 0):
            dm["estado"] = estado
        h_entrada = r.get("hora_entrada")
        h_salida = r.get("hora_salida")
        if h_entrada and h_salida:
            he = _td_to_hours(h_entrada)
            hs = _td_to_hours(h_salida)
            if he is not None and hs is not None and hs > he:
                dm["horas"] = round(hs - he, 1)
    return daily_map


def _compute_asistencia_stats(empleado_id, desde, hasta):
    rows, _ = _get_asistencias_page(1, 50000, empleado_id=empleado_id, fecha_desde=desde, fecha_hasta=hasta)

    totales = {"registros": 0, "ok": 0, "tarde": 0, "ausente": 0, "salida_anticipada": 0}
    jornadas = {"completas": 0, "incompletas": 0}
    horas_jornada = []
    gps_incidencias = 0
    entradas_manuales = 0   # hora_entrada registrada con método manual (admin o app manual)
    salidas_manuales = 0    # hora_salida registrada con método manual

    for r in rows:
        totales["registros"] += 1
        estado = str(r.get("estado") or "").lower()
        if estado in totales:
            totales[estado] += 1

        h_entrada = r.get("hora_entrada")
        h_salida = r.get("hora_salida")

        if h_entrada and h_salida:
            jornadas["completas"] += 1
            he = _td_to_hours(h_entrada)
            hs = _td_to_hours(h_salida)
            if he is not None and hs is not None and hs > he:
                horas_jornada.append(hs - he)
        elif h_entrada:
            jornadas["incompletas"] += 1

        if h_entrada is not None and r.get("gps_ok_entrada") == 0:
            gps_incidencias += 1
        if h_salida is not None and r.get("gps_ok_salida") == 0:
            gps_incidencias += 1

        if h_entrada and str(r.get("metodo_entrada") or "").lower() == "manual":
            entradas_manuales += 1
        if h_salida and str(r.get("metodo_salida") or "").lower() == "manual":
            salidas_manuales += 1

    daily_map = _rows_to_daily_map(rows)

    n = max(totales["registros"], 1)
    dias_laborables = _count_workdays(desde, hasta)
    dias_con_registro = len(daily_map)
    adherencia_pct = round(dias_con_registro * 100 / max(dias_laborables, 1), 1)
    horas_promedio = round(sum(horas_jornada) / len(horas_jornada), 1) if horas_jornada else 0.0
    horas_totales = round(sum(horas_jornada), 1)

    kpis = {
        "puntualidad_pct": round(totales["ok"] * 100 / n, 1),
        "ausentismo_pct": round(totales["ausente"] * 100 / n, 1),
        "no_show_pct": round((totales["ausente"] + totales["salida_anticipada"]) * 100 / n, 1),
        "adherencia_pct": adherencia_pct,
        "horas_promedio": horas_promedio,
        "horas_totales": horas_totales,
        "gps_incidencias": gps_incidencias,
        "dias_laborables": dias_laborables,
        "dias_con_registro": dias_con_registro,
    }

    # Racha actual OK — consecutive OK from most recent date
    sorted_rows = sorted(rows, key=lambda r: str(r.get("fecha") or ""), reverse=True)
    racha_ok = 0
    for r in sorted_rows:
        if str(r.get("estado") or "").lower() == "ok":
            racha_ok += 1
        else:
            break

    # Justificaciones breakdown (all time for employee)
    all_just, _ = _get_justificaciones_page(1, 50000, empleado_id=empleado_id)
    just_aprobadas = sum(1 for j in all_just if str(j.get("estado") or "").lower() == "aprobada")
    just_rechazadas = sum(1 for j in all_just if str(j.get("estado") or "").lower() == "rechazada")
    just_pendientes = sum(1 for j in all_just if str(j.get("estado") or "").lower() == "pendiente")
    tasa_just = round(just_aprobadas * 100 / totales["ausente"], 1) if totales["ausente"] > 0 else 0.0

    justificaciones = {
        "pendientes": just_pendientes,
        "aprobadas": just_aprobadas,
        "rechazadas": just_rechazadas,
        "total": len(all_just),
        "tasa_pct": tasa_just,
    }
    vac_rows, _ = _get_vacaciones_page(empleado_id, 1, 50000, fecha_desde=desde, fecha_hasta=hasta)
    vac_dias = 0
    vac_dates: set = set()  # fechas ISO cubiertas por vacaciones en el período
    for v in vac_rows:
        fd = _to_date(v.get("fecha_desde"))
        fh = _to_date(v.get("fecha_hasta"))
        if fd and fh and fh >= fd:
            vac_dias += (fh - fd).days + 1
            cur_v = fd
            while cur_v <= fh:
                vac_dates.add(cur_v.isoformat())
                cur_v += datetime.timedelta(days=1)
    vacaciones = {"eventos": len(vac_rows), "dias": vac_dias}

    # Ausencias cubiertas por vacaciones (no deben contarse como "sin justificar")
    ausencias_en_vacaciones = sum(
        1 for r in rows
        if str(r.get("estado") or "").lower() == "ausente"
        and str(r.get("fecha") or "")[:10] in vac_dates
    )
    ausencias_sin_just = max(0, totales["ausente"] - just_aprobadas - ausencias_en_vacaciones)
    ausencias = {
        "sin_justificacion": ausencias_sin_just,
        "en_vacaciones": ausencias_en_vacaciones,
    }

    status_labels = [
        ("ok", "OK / Puntual", "ok"),
        ("tarde", "Tardanza", "warning"),
        ("ausente", "Ausente", "danger"),
        ("salida_anticipada", "Salida anticipada", "warning"),
    ]
    asistencia_status_rows = [
        {"label": label, "total": totales[key], "pct": round(totales[key] * 100 / n, 1), "tone": tone}
        for key, label, tone in status_labels
        if totales[key] > 0
    ]

    calendar_weeks, semanas_rows = _build_calendar_grid(daily_map, desde, hasta)

    # Calendario libre: últimos 13 meses hasta hoy, independiente del filtro de KPIs
    today = datetime.date.today()
    cal_end = today
    cal_start = (today.replace(day=1) - datetime.timedelta(days=365)).replace(day=1)
    cal_rows, _ = _get_asistencias_page(
        1, 50000,
        empleado_id=empleado_id,
        fecha_desde=cal_start.isoformat(),
        fecha_hasta=cal_end.isoformat(),
    )
    cal_daily_map = _rows_to_daily_map(cal_rows)
    calendar_months = _build_calendar_months(cal_daily_map, cal_start.isoformat(), cal_end.isoformat())

    # Horario asignado: horas teóricas por día de semana
    teo_por_wd = _get_horas_teoricas_por_dia_semana(empleado_id)  # {0:8.0, 5:4.0, ...} o None

    # Horas promedio por mes — con teóricas calculadas sobre los días efectivamente trabajados
    _horas_mes: dict = {}
    for r in cal_rows:
        fecha = r.get("fecha")
        h_entrada = r.get("hora_entrada")
        h_salida = r.get("hora_salida")
        if not fecha or not h_entrada or not h_salida:
            continue
        he = _td_to_hours(h_entrada)
        hs = _td_to_hours(h_salida)
        if he is None or hs is None or hs <= he:
            continue
        ds = str(fecha)[:10]
        mes_key = ds[:7]
        wd = datetime.date.fromisoformat(ds).weekday()  # 0=Lun … 6=Dom

        if mes_key not in _horas_mes:
            _horas_mes[mes_key] = {"sum_horas": 0.0, "jornadas": 0, "sum_teo": 0.0, "jornadas_teo": 0}
        _horas_mes[mes_key]["sum_horas"] += hs - he
        _horas_mes[mes_key]["jornadas"] += 1

        # Acumular teóricas solo para días que tienen horario definido
        if teo_por_wd and wd in teo_por_wd:
            _horas_mes[mes_key]["sum_teo"] += teo_por_wd[wd]
            _horas_mes[mes_key]["jornadas_teo"] += 1

    horas_promedio_por_mes = []
    for key in sorted(_horas_mes.keys()):
        d = _horas_mes[key]
        year, month = int(key[:4]), int(key[5:7])
        promedio = round(d["sum_horas"] / d["jornadas"], 1) if d["jornadas"] > 0 else 0.0
        # Teóricas: promedio de lo esperado en los mismos días trabajados ese mes
        teo_prom = (
            round(d["sum_teo"] / d["jornadas_teo"], 1)
            if d["jornadas_teo"] > 0 else None
        )
        horas_promedio_por_mes.append({
            "key": key,
            "mes": f"{_MONTH_NAMES[month]} {year}",
            "promedio": promedio,
            "jornadas": d["jornadas"],
            "teoricas_prom": teo_prom,  # teóricas reales para ese mes según días trabajados
        })

    # Descripción legible del horario para el template
    horario_desc = None
    if teo_por_wd:
        _dias_names = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        horario_desc = ", ".join(
            f"{_dias_names[wd]}: {h}h"
            for wd, h in sorted(teo_por_wd.items())
        )

    # Estados por mes — para stacked bar chart (últimos 13 meses, mismos datos que el calendario)
    _estados_mes: dict = {}
    for r in cal_rows:
        fecha = r.get("fecha")
        if not fecha:
            continue
        mes_key = str(fecha)[:7]
        estado = str(r.get("estado") or "none").lower()
        if mes_key not in _estados_mes:
            _estados_mes[mes_key] = {"ok": 0, "tarde": 0, "ausente": 0, "salida_anticipada": 0, "total": 0}
        _estados_mes[mes_key]["total"] += 1
        if estado in _estados_mes[mes_key]:
            _estados_mes[mes_key][estado] += 1

    estados_por_mes = []
    for key in sorted(_estados_mes.keys()):
        year, month = int(key[:4]), int(key[5:7])
        d = _estados_mes[key]
        total = max(d["total"], 1)
        estados_por_mes.append({
            "key": key,
            "mes": f"{_MONTH_NAMES[month]} {year}",
            "ok": d["ok"],
            "tarde": d["tarde"],
            "ausente": d["ausente"],
            "salida_anticipada": d["salida_anticipada"],
            "total": d["total"],
            "ok_pct": round(d["ok"] * 100 / total, 1),
            "tarde_pct": round(d["tarde"] * 100 / total, 1),
            "ausente_pct": round(d["ausente"] * 100 / total, 1),
            "sa_pct": round(d["salida_anticipada"] * 100 / total, 1),
        })

    # ── Calidad de fichada ───────────────────────────────────────────────────
    # Por cada día hábil del horario: ambos fichados=100%, uno solo=50%, ninguno=0%
    # Si no hay horario asignado: evalúa todos los días con registro.

    def _calidad_per_range(date_rows_map, teo_wd, d_start, d_end, skip_dates=None):
        """Retorna (score_sum, n_dias_evaluados). skip_dates excluye fechas ISO (ej: vacaciones)."""
        score, n = 0, 0
        skip = skip_dates or set()
        if teo_wd:
            cur = d_start
            while cur <= d_end:
                ds = cur.isoformat()
                if cur.weekday() in teo_wd and ds not in skip:
                    dr = date_rows_map.get(ds, [])
                    he = any(r.get("hora_entrada") for r in dr)
                    hs = any(r.get("hora_salida") for r in dr)
                    score += 100 if (he and hs) else (50 if (he or hs) else 0)
                    n += 1
                cur += datetime.timedelta(days=1)
        else:
            d0, d1 = d_start.isoformat(), d_end.isoformat()
            for ds, dr in date_rows_map.items():
                if d0 <= ds <= d1 and ds not in skip:
                    he = any(r.get("hora_entrada") for r in dr)
                    hs = any(r.get("hora_salida") for r in dr)
                    score += 100 if (he and hs) else (50 if (he or hs) else 0)
                    n += 1
        return score, n

    # Mapas fecha→lista de rows
    _period_drows: dict = {}
    for r in rows:
        ds = str(r.get("fecha") or "")[:10]
        if ds:
            _period_drows.setdefault(ds, []).append(r)

    _cal_drows: dict = {}
    for r in cal_rows:
        ds = str(r.get("fecha") or "")[:10]
        if ds:
            _cal_drows.setdefault(ds, []).append(r)

    # KPI del período seleccionado
    try:
        _kpi_desde = datetime.date.fromisoformat(str(desde)[:10])
        _kpi_hasta = min(datetime.date.fromisoformat(str(hasta)[:10]), today)
    except (ValueError, TypeError):
        _kpi_desde = _kpi_hasta = today

    # Vacaciones de los últimos 13 meses para excluir de calidad mensual
    _all_vac, _ = _get_vacaciones_page(empleado_id, 1, 50000,
                                        fecha_desde=cal_start.isoformat(),
                                        fecha_hasta=cal_end.isoformat())
    _all_vac_dates: set = set()
    for _v in _all_vac:
        _vfd = _to_date(_v.get("fecha_desde"))
        _vfh = _to_date(_v.get("fecha_hasta"))
        if _vfd and _vfh:
            _vc = _vfd
            while _vc <= _vfh:
                _all_vac_dates.add(_vc.isoformat())
                _vc += datetime.timedelta(days=1)

    _cscore, _cn = _calidad_per_range(_period_drows, teo_por_wd, _kpi_desde, _kpi_hasta,
                                       skip_dates=vac_dates)
    calidad_fichada_pct = round(_cscore / _cn, 1) if _cn > 0 else None
    calidad_fichada_n = _cn

    # Por mes — últimos 13 meses (excluye días de vacaciones)
    calidad_por_mes = []
    _cal_mes_keys = sorted({ds[:7] for ds in _cal_drows})
    for _mk in _cal_mes_keys:
        _my, _mm = int(_mk[:4]), int(_mk[5:7])
        _ms = datetime.date(_my, _mm, 1)
        _me = (
            datetime.date(_my + 1, 1, 1) if _mm == 12
            else datetime.date(_my, _mm + 1, 1)
        ) - datetime.timedelta(days=1)
        _me = min(_me, today)
        _sc, _nd = _calidad_per_range(_cal_drows, teo_por_wd, _ms, _me,
                                       skip_dates=_all_vac_dates)
        calidad_por_mes.append({
            "key": _mk,
            "mes": f"{_MONTH_NAMES[_mm]} {_my}",
            "calidad_pct": round(_sc / _nd, 1) if _nd > 0 else None,
            "dias_evaluados": _nd,
        })

    # ── Panel de alertas consolidado ────────────────────────────────────────
    alertas = []

    if just_pendientes > 0:
        alertas.append({
            "tipo": "warn",
            "icono": "⏳",
            "msg": f"{just_pendientes} justificación(es) pendiente(s) de revisión",
            "link_label": "Ver justificaciones",
            "link_key": "justificaciones",
        })

    if ausencias_sin_just > 0:
        alertas.append({
            "tipo": "danger",
            "icono": "✖",
            "msg": f"{ausencias_sin_just} ausencia(s) sin justificación aprobada en el periodo",
            "link_label": None,
            "link_key": None,
        })

    total_manuales = entradas_manuales + salidas_manuales
    if total_manuales > 0:
        partes = []
        if entradas_manuales:
            partes.append(f"{entradas_manuales} entrada(s)")
        if salidas_manuales:
            partes.append(f"{salidas_manuales} salida(s)")
        alertas.append({
            "tipo": "info",
            "icono": "✎",
            "msg": f"{total_manuales} fichada(s) completada(s) manualmente ({', '.join(partes)}) — no por QR",
            "link_label": "Ver asistencias",
            "link_key": "asistencias",
        })

    if gps_incidencias > 0:
        alertas.append({
            "tipo": "warn",
            "icono": "📍",
            "msg": f"{gps_incidencias} fichada(s) con GPS fuera del rango permitido",
            "link_label": None,
            "link_key": None,
        })

    if jornadas["incompletas"] > 0:
        alertas.append({
            "tipo": "warn",
            "icono": "⏱",
            "msg": f"{jornadas['incompletas']} jornada(s) incompleta(s): entrada registrada pero sin salida",
            "link_label": None,
            "link_key": None,
        })

    if calidad_fichada_pct is not None and calidad_fichada_pct < 70:
        alertas.append({
            "tipo": "danger",
            "icono": "📋",
            "msg": f"Calidad de fichada baja: {calidad_fichada_pct:.1f}% (meta: ≥ 90%)",
            "link_label": None,
            "link_key": None,
        })

    return {
        "asistencia": {
            "totales": totales,
            "kpis": kpis,
            "jornadas": jornadas,
            "justificaciones": justificaciones,
            "ausencias": ausencias,
            "vacaciones": vacaciones,
            "racha_ok": racha_ok,
        },
        "asistencia_status_rows": asistencia_status_rows,
        "calendar_weeks": calendar_weeks,
        "calendar_months": calendar_months,
        "semanas_rows": semanas_rows,
        "horas_promedio_por_mes": horas_promedio_por_mes,
        "horario_desc": horario_desc,
        "estados_por_mes": estados_por_mes,
        "calidad_fichada_pct": calidad_fichada_pct,
        "calidad_fichada_n": calidad_fichada_n,
        "calidad_por_mes": calidad_por_mes,
        "alertas": alertas,
        "_rows": rows,
    }


def _compute_legajo_stats(empleado_id, desde, hasta):
    all_events = get_eventos_by_empleado(empleado_id, include_anulados=True)

    hist_vigentes = sum(1 for e in all_events if str(e.get("estado") or "").lower() == "vigente")
    hist_anulados = len(all_events) - hist_vigentes

    desde_date = _to_date(desde)
    hasta_date = _to_date(hasta)

    def _in_period(ev):
        fe = _to_date(ev.get("fecha_evento"))
        if fe is None:
            return False
        if desde_date and fe < desde_date:
            return False
        if hasta_date and fe > hasta_date:
            return False
        return True

    periodo_events = [e for e in all_events if _in_period(e)]
    periodo_vigentes = [e for e in periodo_events if str(e.get("estado") or "").lower() == "vigente"]
    per_anulados = len(periodo_events) - len(periodo_vigentes)

    tipo_counts = defaultdict(lambda: {"label": "", "total": 0})
    for e in periodo_vigentes:
        tid = e.get("tipo_id")
        tipo_counts[tid]["label"] = e.get("tipo_nombre") or e.get("tipo_codigo") or str(tid)
        tipo_counts[tid]["total"] += 1

    tipo_total = sum(d["total"] for d in tipo_counts.values()) or 1
    por_tipo = sorted(
        [{"label": d["label"], "total": d["total"], "pct": round(d["total"] * 100 / tipo_total, 1)}
         for d in tipo_counts.values()],
        key=lambda x: -x["total"],
    )

    sev_counts = defaultdict(int)
    for e in periodo_vigentes:
        sev_counts[str(e.get("severidad") or "sin severidad").lower()] += 1

    sev_total = sum(sev_counts.values()) or 1
    por_severidad = sorted(
        [{"label": sev, "total": cnt, "pct": round(cnt * 100 / sev_total, 1)}
         for sev, cnt in sev_counts.items()],
        key=lambda x: -x["total"],
    )

    graves = sum(1 for e in periodo_vigentes if str(e.get("severidad") or "").lower() == "grave")
    media = sum(1 for e in periodo_vigentes if str(e.get("severidad") or "").lower() == "media")
    leve = sum(1 for e in periodo_vigentes if str(e.get("severidad") or "").lower() == "leve")

    return {
        "historico": {"total": len(all_events), "vigentes": hist_vigentes, "anulados": hist_anulados},
        "periodo": {
            "total": len(periodo_events),
            "vigentes": len(periodo_vigentes),
            "anulados": per_anulados,
            "graves": graves,
            "media": media,
            "leve": leve,
            "tipos_unicos": len(tipo_counts),
        },
        "por_tipo": por_tipo,
        "por_severidad": por_severidad,
        "recientes_periodo": periodo_vigentes[:10],
    }


def _parse_hhmm(value: str) -> float | None:
    """Convierte 'HH:MM' a horas decimales. None si formato inválido."""
    s = str(value or "").strip()
    if len(s) < 5 or s[2] != ":":
        return None
    try:
        return int(s[:2]) + int(s[3:5]) / 60
    except ValueError:
        return None


def _get_horas_teoricas_por_dia_semana(empleado_id: int) -> dict[int, float] | None:
    """
    Devuelve {dia_semana (0=Lun … 6=Dom): horas_teoricas} según el horario
    actualmente asignado al empleado.
    Ejemplo: {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 4.0}
    Retorna None si el empleado no tiene horario asignado.
    """
    try:
        asignacion = _get_horario_actual(empleado_id)
        if not asignacion:
            return None
        horario = _get_horario_estructurado(asignacion["horario_id"])
        if not horario or not horario.get("dias"):
            return None

        result: dict[int, float] = {}
        for dia in horario["dias"]:
            wd = dia.get("dia_semana")
            if wd is None:
                continue
            dia_horas = 0.0
            for bloque in dia.get("bloques", []):
                he = _parse_hhmm(bloque.get("entrada"))
                hs = _parse_hhmm(bloque.get("salida"))
                if he is not None and hs is not None and hs > he:
                    dia_horas += hs - he
            if dia_horas > 0:
                result[int(wd)] = round(dia_horas, 2)

        return result if result else None
    except Exception:
        return None


def _build_dashboard_context(empleado_id, q, desde, hasta, periodo, solo_activos):
    empleados, empleados_total = _get_empleados_page(
        1, 50,
        include_inactive=not solo_activos,
        search=q or None,
    )

    empleado = None
    asistencia = {"totales": {}, "kpis": {}, "jornadas": {}, "justificaciones": {}, "ausencias": {}, "vacaciones": {}, "racha_ok": 0}
    legajo = {"historico": {}, "periodo": {}, "por_tipo": [], "por_severidad": [], "recientes_periodo": []}
    asistencia_status_rows = []
    calendar_weeks = []
    calendar_months = []
    semanas_rows = []
    asistencia_rows = []
    horas_promedio_por_mes = []
    horario_desc = None
    estados_por_mes = []
    calidad_fichada_pct = None
    calidad_fichada_n = 0
    calidad_por_mes = []
    alertas = []

    if empleado_id:
        empleado = get_empleado_by_id(empleado_id)
        if empleado:
            stats = _compute_asistencia_stats(empleado_id, desde, hasta)
            asistencia = stats["asistencia"]
            asistencia_status_rows = stats["asistencia_status_rows"]
            calendar_weeks = stats["calendar_weeks"]
            calendar_months = stats["calendar_months"]
            semanas_rows = stats["semanas_rows"]
            horas_promedio_por_mes = stats["horas_promedio_por_mes"]
            horario_desc = stats["horario_desc"]
            estados_por_mes = stats["estados_por_mes"]
            calidad_fichada_pct = stats["calidad_fichada_pct"]
            calidad_fichada_n = stats["calidad_fichada_n"]
            calidad_por_mes = stats["calidad_por_mes"]
            alertas = stats["alertas"]
            asistencia_rows = stats["_rows"]
            legajo = _compute_legajo_stats(empleado_id, desde, hasta)

    return {
        "empleado": empleado,
        "empleado_id": empleado_id,
        "empleados": empleados,
        "empleados_total": empleados_total,
        "asistencia": asistencia,
        "legajo": legajo,
        "asistencia_status_rows": asistencia_status_rows,
        "calendar_weeks": calendar_weeks,
        "calendar_months": calendar_months,
        "semanas_rows": semanas_rows,
        "horas_promedio_por_mes": horas_promedio_por_mes,
        "horario_desc": horario_desc,
        "estados_por_mes": estados_por_mes,
        "calidad_fichada_pct": calidad_fichada_pct,
        "calidad_fichada_n": calidad_fichada_n,
        "calidad_por_mes": calidad_por_mes,
        "alertas": alertas,
        "desde": desde,
        "hasta": hasta,
        "periodo": periodo,
        "q": q or "",
        "solo_activos": solo_activos,
        "errors": [],
        "_asistencia_rows": asistencia_rows,
    }


# ---------------------------------------------------------------------------
# Dashboard por empleado — routes
# ---------------------------------------------------------------------------

@legajos_bp.route("/dashboard-empleado")
@role_required("admin", "rrhh", "supervisor")
def dashboard_empleado():
    q = str(request.args.get("q") or "").strip() or None
    empleado_id = request.args.get("empleado_id", type=int)
    periodo_raw = str(request.args.get("periodo") or "30d").strip()
    if periodo_raw not in {"7d", "30d", "90d", "mes_actual", "anio_actual", "custom"}:
        periodo_raw = "30d"
    desde_raw = str(request.args.get("desde") or "").strip() or None
    hasta_raw = str(request.args.get("hasta") or "").strip() or None
    solo_activos = bool(request.args.get("solo_activos"))

    desde, hasta, periodo = _resolve_period(periodo_raw, desde_raw, hasta_raw)
    ctx = _build_dashboard_context(empleado_id, q, desde, hasta, periodo, solo_activos)

    return render_template("legajos/dashboard_empleado.html", **ctx)


@legajos_bp.route("/dashboard-empleado/export.csv")
@role_required("admin", "rrhh", "supervisor")
def dashboard_empleado_export_csv():
    q = str(request.args.get("q") or "").strip() or None
    empleado_id = request.args.get("empleado_id", type=int)
    periodo_raw = str(request.args.get("periodo") or "30d").strip()
    if periodo_raw not in {"7d", "30d", "90d", "mes_actual", "anio_actual", "custom"}:
        periodo_raw = "30d"
    desde_raw = str(request.args.get("desde") or "").strip() or None
    hasta_raw = str(request.args.get("hasta") or "").strip() or None
    solo_activos = bool(request.args.get("solo_activos"))

    desde, hasta, periodo = _resolve_period(periodo_raw, desde_raw, hasta_raw)

    if not empleado_id:
        return redirect(url_for("legajos.dashboard_empleado"))

    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        abort(404)

    stats = _compute_asistencia_stats(empleado_id, desde, hasta)
    legajo = _compute_legajo_stats(empleado_id, desde, hasta)
    asistencia = stats["asistencia"]
    rows = stats["_rows"]
    eventos = legajo["recientes_periodo"]

    out = io.StringIO()
    writer = csv.writer(out)

    writer.writerow(["Dashboard empleado"])
    writer.writerow(["Empleado", f"{empleado.get('apellido')} {empleado.get('nombre')}"])
    writer.writerow(["DNI", empleado.get("dni")])
    writer.writerow(["Periodo", f"{desde} a {hasta}"])
    writer.writerow([])

    writer.writerow(["KPIs de asistencia"])
    writer.writerow(["Registros", asistencia["totales"].get("registros", 0)])
    writer.writerow(["OK / Puntual", asistencia["totales"].get("ok", 0)])
    writer.writerow(["Tardanzas", asistencia["totales"].get("tarde", 0)])
    writer.writerow(["Ausentes", asistencia["totales"].get("ausente", 0)])
    writer.writerow(["Salida anticipada", asistencia["totales"].get("salida_anticipada", 0)])
    writer.writerow(["Puntualidad %", asistencia["kpis"].get("puntualidad_pct", 0)])
    writer.writerow(["Ausentismo %", asistencia["kpis"].get("ausentismo_pct", 0)])
    writer.writerow(["Justificaciones pendientes", asistencia["justificaciones"].get("pendientes", 0)])
    writer.writerow(["Vacaciones (eventos)", asistencia["vacaciones"].get("eventos", 0)])
    writer.writerow(["Vacaciones (dias)", asistencia["vacaciones"].get("dias", 0)])
    writer.writerow([])

    writer.writerow(["Legajo"])
    writer.writerow(["Historico total", legajo["historico"].get("total", 0)])
    writer.writerow(["Historico vigentes", legajo["historico"].get("vigentes", 0)])
    writer.writerow(["Periodo total", legajo["periodo"].get("total", 0)])
    writer.writerow(["Periodo vigentes", legajo["periodo"].get("vigentes", 0)])
    writer.writerow([])

    writer.writerow(["Detalle asistencias"])
    writer.writerow(["Fecha", "Estado", "Hora entrada", "Hora salida"])
    for r in rows:
        writer.writerow([r.get("fecha"), r.get("estado"), r.get("hora_entrada"), r.get("hora_salida")])
    writer.writerow([])

    writer.writerow(["Eventos de legajo (periodo vigentes)"])
    writer.writerow(["Fecha evento", "Tipo", "Titulo", "Severidad", "Estado"])
    for ev in eventos:
        writer.writerow([
            ev.get("fecha_evento"),
            ev.get("tipo_nombre") or ev.get("tipo_codigo"),
            ev.get("titulo") or "",
            ev.get("severidad") or "",
            ev.get("estado") or "",
        ])

    csv_content = "\ufeff" + out.getvalue()
    nombre = f"{empleado.get('apellido', '')}_{empleado.get('nombre', '')}".replace(" ", "_")
    filename = f"dashboard_{nombre}_{desde}_{hasta}.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@legajos_bp.route("/dashboard-empleado/export.xls")
@role_required("admin", "rrhh", "supervisor")
def dashboard_empleado_export_xls():
    # Return the same CSV with Excel-compatible content-type
    q = str(request.args.get("q") or "").strip() or None
    empleado_id = request.args.get("empleado_id", type=int)
    periodo_raw = str(request.args.get("periodo") or "30d").strip()
    if periodo_raw not in {"7d", "30d", "90d", "mes_actual", "anio_actual", "custom"}:
        periodo_raw = "30d"
    desde_raw = str(request.args.get("desde") or "").strip() or None
    hasta_raw = str(request.args.get("hasta") or "").strip() or None
    solo_activos = bool(request.args.get("solo_activos"))

    desde, hasta, periodo = _resolve_period(periodo_raw, desde_raw, hasta_raw)

    if not empleado_id:
        return redirect(url_for("legajos.dashboard_empleado"))

    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        abort(404)

    stats = _compute_asistencia_stats(empleado_id, desde, hasta)
    legajo = _compute_legajo_stats(empleado_id, desde, hasta)
    asistencia = stats["asistencia"]
    rows = stats["_rows"]
    eventos = legajo["recientes_periodo"]

    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t")

    writer.writerow(["Empleado", f"{empleado.get('apellido')} {empleado.get('nombre')}", "DNI", empleado.get("dni")])
    writer.writerow(["Periodo", f"{desde} a {hasta}"])
    writer.writerow([])
    writer.writerow(["Registros", "OK", "Tardanzas", "Ausentes", "Salida anticipada", "Puntualidad %", "Ausentismo %"])
    writer.writerow([
        asistencia["totales"].get("registros", 0),
        asistencia["totales"].get("ok", 0),
        asistencia["totales"].get("tarde", 0),
        asistencia["totales"].get("ausente", 0),
        asistencia["totales"].get("salida_anticipada", 0),
        asistencia["kpis"].get("puntualidad_pct", 0),
        asistencia["kpis"].get("ausentismo_pct", 0),
    ])
    writer.writerow([])
    writer.writerow(["Fecha", "Estado", "Hora entrada", "Hora salida"])
    for r in rows:
        writer.writerow([r.get("fecha"), r.get("estado"), r.get("hora_entrada"), r.get("hora_salida")])
    writer.writerow([])
    writer.writerow(["Fecha evento", "Tipo", "Titulo", "Severidad", "Estado"])
    for ev in eventos:
        writer.writerow([
            ev.get("fecha_evento"),
            ev.get("tipo_nombre") or ev.get("tipo_codigo"),
            ev.get("titulo") or "",
            ev.get("severidad") or "",
            ev.get("estado") or "",
        ])

    nombre = f"{empleado.get('apellido', '')}_{empleado.get('nombre', '')}".replace(" ", "_")
    filename = f"dashboard_{nombre}_{desde}_{hasta}.xls"
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="application/vnd.ms-excel; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@legajos_bp.route("/dashboard-empleado/print")
@role_required("admin", "rrhh", "supervisor")
def dashboard_empleado_print():
    q = str(request.args.get("q") or "").strip() or None
    empleado_id = request.args.get("empleado_id", type=int)
    periodo_raw = str(request.args.get("periodo") or "30d").strip()
    if periodo_raw not in {"7d", "30d", "90d", "mes_actual", "anio_actual", "custom"}:
        periodo_raw = "30d"
    desde_raw = str(request.args.get("desde") or "").strip() or None
    hasta_raw = str(request.args.get("hasta") or "").strip() or None
    solo_activos = bool(request.args.get("solo_activos"))
    auto_print = bool(request.args.get("auto_print"))

    desde, hasta, periodo = _resolve_period(periodo_raw, desde_raw, hasta_raw)
    ctx = _build_dashboard_context(empleado_id, q, desde, hasta, periodo, solo_activos)
    ctx["auto_print"] = auto_print

    return render_template("legajos/dashboard_empleado.html", **ctx)
