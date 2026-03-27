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


def _compute_asistencia_stats(empleado_id, desde, hasta):
    rows, _ = _get_asistencias_page(1, 50000, empleado_id=empleado_id, fecha_desde=desde, fecha_hasta=hasta)

    totales = {"registros": 0, "ok": 0, "tarde": 0, "ausente": 0, "salida_anticipada": 0}
    jornadas = {"completas": 0, "incompletas": 0}
    daily_map = {}
    horas_jornada = []
    gps_incidencias = 0

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

        fecha = r.get("fecha")
        if fecha:
            ds = str(fecha)[:10]
            if ds not in daily_map:
                daily_map[ds] = {"registros": 0, "tardes": 0, "ausentes": 0, "salidas": 0, "ok": 0, "estado": "none", "horas": None}
            dm = daily_map[ds]
            dm["registros"] += 1
            if estado == "tarde":
                dm["tardes"] += 1
            elif estado == "ausente":
                dm["ausentes"] += 1
            elif estado == "salida_anticipada":
                dm["salidas"] += 1
            elif estado == "ok":
                dm["ok"] += 1
            # Dominant estado: ausente > salida_anticipada > tarde > ok
            _rank = {"ausente": 4, "salida_anticipada": 3, "tarde": 2, "ok": 1}
            if _rank.get(estado, 0) > _rank.get(dm["estado"], 0):
                dm["estado"] = estado
            if h_entrada and h_salida:
                he = _td_to_hours(h_entrada)
                hs = _td_to_hours(h_salida)
                if he is not None and hs is not None and hs > he:
                    dm["horas"] = round(hs - he, 1)

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
    ausencias = {"sin_justificacion": max(0, totales["ausente"] - just_aprobadas)}

    vac_rows, _ = _get_vacaciones_page(empleado_id, 1, 50000, fecha_desde=desde, fecha_hasta=hasta)
    vac_dias = 0
    for v in vac_rows:
        fd = _to_date(v.get("fecha_desde"))
        fh = _to_date(v.get("fecha_hasta"))
        if fd and fh and fh >= fd:
            vac_dias += (fh - fd).days + 1
    vacaciones = {"eventos": len(vac_rows), "dias": vac_dias}

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
        "semanas_rows": semanas_rows,
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
    semanas_rows = []
    asistencia_rows = []

    if empleado_id:
        empleado = get_empleado_by_id(empleado_id)
        if empleado:
            stats = _compute_asistencia_stats(empleado_id, desde, hasta)
            asistencia = stats["asistencia"]
            asistencia_status_rows = stats["asistencia_status_rows"]
            calendar_weeks = stats["calendar_weeks"]
            semanas_rows = stats["semanas_rows"]
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
        "semanas_rows": semanas_rows,
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
