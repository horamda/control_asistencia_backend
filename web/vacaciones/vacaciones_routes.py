import csv
import datetime
import io

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from repositories.empleado_repository import get_all as get_empleados
from repositories.sector_repository import get_all as get_sectores
from repositories.vacacion_repository import get_all
from repositories.vacaciones_repository import (
    get_movimiento_by_id,
    get_movimientos_export,
    get_movimientos_gantt_year,
    get_movimientos_page,
    get_movimientos_summary,
)
from services.vacaciones_service import (
    VacacionesError,
    VacacionesSaldoInsuficienteError,
    aprobar_movimiento_vacaciones,
    calcular_resumen_vacaciones,
    cancelar_movimiento_vacaciones,
    crear_compensatorios_bulk,
    crear_movimiento_vacaciones_admin,
    editar_movimiento_vacaciones_aprobado,
    editar_movimiento_vacaciones_pendiente,
    rechazar_movimiento_vacaciones,
)
from utils.audit import log_audit
from web.auth.decorators import role_required

vacaciones_bp = Blueprint("vacaciones", __name__, url_prefix="/vacaciones")
TIPOS_MOVIMIENTO = {"tomado", "compensatorio", "ajuste"}
ESTADOS_MOVIMIENTO = {"pendiente", "aprobado", "rechazado"}


def _current_year_options():
    current_year = datetime.date.today().year
    return list(range(current_year + 1, current_year - 5, -1))


def _month_options():
    return [
        (1, "Enero"),
        (2, "Febrero"),
        (3, "Marzo"),
        (4, "Abril"),
        (5, "Mayo"),
        (6, "Junio"),
        (7, "Julio"),
        (8, "Agosto"),
        (9, "Septiembre"),
        (10, "Octubre"),
        (11, "Noviembre"),
        (12, "Diciembre"),
    ]


def _extract_filters(args):
    filters = {
        "page": args.get("page", 1, type=int) or 1,
        "per_page": args.get("per", 20, type=int) or 20,
        "empleado_id": args.get("empleado_id", type=int),
        "sector_id": args.get("sector_id", type=int),
        "search": (args.get("q") or "").strip() or None,
        "estado": (args.get("estado") or "").strip().lower() or None,
        "tipo": (args.get("tipo") or "").strip().lower() or None,
        "anio": args.get("anio", type=int) or datetime.date.today().year,
        "mes": args.get("mes", type=int),
    }
    error = None
    if filters["estado"] and filters["estado"] not in ESTADOS_MOVIMIENTO:
        error = "Estado invalido."
        filters["estado"] = None
    if filters["tipo"] and filters["tipo"] not in TIPOS_MOVIMIENTO:
        error = "Tipo de movimiento invalido."
        filters["tipo"] = None
    if filters["anio"] < 2000 or filters["anio"] > 2100:
        error = "Anio invalido."
        filters["anio"] = datetime.date.today().year
    if filters["mes"] is not None and filters["mes"] not in range(1, 13):
        error = "Mes invalido."
        filters["mes"] = None
    filters["per_page"] = max(1, min(int(filters["per_page"]), 100))
    filters["page"] = max(1, int(filters["page"]))
    return filters, error


def _movimiento_form_data(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "anio": int(form.get("anio")) if (form.get("anio") or "").isdigit() else datetime.date.today().year,
        "tipo": (form.get("tipo") or "").strip().lower(),
        "dias": (form.get("dias") or "").strip(),
        "fecha_desde": (form.get("fecha_desde") or "").strip(),
        "fecha_hasta": (form.get("fecha_hasta") or "").strip(),
        "estado": (form.get("estado") or "aprobado").strip().lower(),
        "observacion": (form.get("observacion") or "").strip(),
    }


def _extract(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "fecha_desde": (form.get("fecha_desde") or "").strip(),
        "fecha_hasta": (form.get("fecha_hasta") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip(),
    }


def _validate(form):
    errors = []
    if not (form.get("empleado_id") or "").isdigit():
        errors.append("Empleado es requerido.")
    if not (form.get("fecha_desde") or "").strip():
        errors.append("Fecha desde es requerida.")
    if not (form.get("fecha_hasta") or "").strip():
        errors.append("Fecha hasta es requerida.")
    return errors


def _parse_empleado_activo(value: str | None):
    raw = str(value or "1").strip().lower()
    if raw in {"all", "todos", "todas", ""}:
        return None, "all"
    if raw in {"1", "true", "activo", "activos"}:
        return 1, "1"
    if raw in {"0", "false", "inactivo", "inactivos"}:
        return 0, "0"
    return 1, "1"


def _extract_reporte_filters(args):
    anio = args.get("anio", type=int) or datetime.date.today().year
    if anio < 2000 or anio > 2100:
        anio = datetime.date.today().year
    sector_id = args.get("sector_id", type=int) or args.get("area_id", type=int)
    activo, activo_raw = _parse_empleado_activo(args.get("activo"))
    return {
        "anio": anio,
        "sector_id": sector_id,
        "search": (args.get("q") or "").strip() or None,
        "activo": activo,
        "activo_raw": activo_raw,
    }


def _matches_reporte_filters(empleado: dict, filters: dict) -> bool:
    activo = filters.get("activo")
    if activo in (0, 1) and int(empleado.get("activo") or 0) != int(activo):
        return False

    sector_id = filters.get("sector_id")
    if sector_id and int(empleado.get("sector_id") or 0) != int(sector_id):
        return False

    search = str(filters.get("search") or "").strip().lower()
    if search:
        haystack = " ".join(
            str(empleado.get(key) or "")
            for key in ("apellido", "nombre", "dni", "legajo", "sector_nombre", "empresa_nombre")
        ).lower()
        if search not in haystack:
            return False
    return True


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _build_reporte_vacaciones(filters: dict):
    empleados = [
        e for e in get_empleados(include_inactive=True)
        if _matches_reporte_filters(e, filters)
    ]
    empleados.sort(key=lambda e: (
        str(e.get("sector_nombre") or "").lower(),
        str(e.get("apellido") or "").lower(),
        str(e.get("nombre") or "").lower(),
    ))

    rows = []
    totals = {
        "empleados": len(empleados),
        "con_error": 0,
        "dias_base": 0.0,
        "dias_compensatorios": 0.0,
        "dias_ajustes": 0.0,
        "dias_corresponden": 0.0,
        "dias_tomados": 0.0,
        "dias_pendientes": 0.0,
        "dias_disponibles": 0.0,
        "dias_disponibles_con_pendientes": 0.0,
    }

    for empleado in empleados:
        row = {
            "empleado_id": empleado.get("id"),
            "empresa_nombre": empleado.get("empresa_nombre"),
            "sector_nombre": empleado.get("sector_nombre"),
            "puesto_nombre": empleado.get("puesto_nombre"),
            "apellido": empleado.get("apellido"),
            "nombre": empleado.get("nombre"),
            "dni": empleado.get("dni"),
            "legajo": empleado.get("legajo"),
            "estado": empleado.get("estado"),
            "activo": bool(empleado.get("activo")),
            "error": None,
        }
        try:
            resumen = calcular_resumen_vacaciones(int(empleado["id"]), int(filters["anio"]))
        except VacacionesError as exc:
            row["error"] = str(exc)
            totals["con_error"] += 1
        else:
            vac = resumen["vacaciones"]
            row.update(vac)
            row["dias_pendientes_por_tomar"] = _number(vac.get("dias_disponibles"))
            for key in (
                "dias_base",
                "dias_compensatorios",
                "dias_ajustes",
                "dias_corresponden",
                "dias_tomados",
                "dias_pendientes",
                "dias_disponibles",
                "dias_disponibles_con_pendientes",
            ):
                totals[key] += _number(vac.get(key))
        rows.append(row)

    totals["dias_pendientes_por_tomar"] = totals["dias_disponibles"]

    return rows, totals


@vacaciones_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    filters, filter_error = _extract_filters(request.args)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    if not error:
        error = filter_error

    movimientos, total = get_movimientos_page(
        page=filters["page"],
        per_page=filters["per_page"],
        empleado_id=filters["empleado_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        mes=filters["mes"],
    )
    summary = get_movimientos_summary(
        empleado_id=filters["empleado_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        mes=filters["mes"],
    )
    empleados = get_empleados(include_inactive=True)
    sectores = get_sectores(include_inactive=True)
    vacaciones = get_all()
    saldo = None
    if filters["empleado_id"]:
        try:
            saldo = calcular_resumen_vacaciones(filters["empleado_id"], filters["anio"])
        except VacacionesError as exc:
            error = error or str(exc)

    return render_template(
        "vacaciones/listado.html",
        vacaciones=vacaciones,
        movimientos=movimientos,
        total=total,
        summary=summary,
        empleados=empleados,
        sectores=sectores,
        saldo=saldo,
        page=filters["page"],
        per_page=filters["per_page"],
        empleado_id=filters["empleado_id"],
        sector_id=filters["sector_id"],
        q=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        mes=filters["mes"],
        years=_current_year_options(),
        months=_month_options(),
        error=error,
        msg=msg,
    )


@vacaciones_bp.route("/movimientos/export.csv")
@role_required("admin", "rrhh")
def movimientos_export_csv():
    filters, error = _extract_filters(request.args)
    if error:
        return redirect(url_for("vacaciones.listado", error=error))

    rows = get_movimientos_export(
        empleado_id=filters["empleado_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        mes=filters["mes"],
        limit=10000,
    )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "id",
        "empresa",
        "sector",
        "empleado",
        "dni",
        "anio",
        "tipo",
        "dias",
        "estado",
        "fecha_desde",
        "fecha_hasta",
        "observacion",
        "motivo_resolucion",
        "origen_movimiento_id",
        "revertido_por_movimiento_id",
        "created_at",
    ])
    for row in rows:
        writer.writerow([
            row.get("id"),
            row.get("empresa_nombre") or "",
            row.get("sector_nombre") or "",
            f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip(),
            row.get("dni") or "",
            row.get("anio") or "",
            row.get("tipo") or "",
            row.get("dias") or "",
            row.get("estado") or "",
            row.get("fecha_desde") or "",
            row.get("fecha_hasta") or "",
            row.get("observacion") or "",
            row.get("motivo_resolucion") or "",
            row.get("origen_movimiento_id") or "",
            row.get("revertido_por_movimiento_id") or "",
            row.get("created_at") or "",
        ])

    filename = f"vacaciones_movimientos_{datetime.date.today().isoformat()}.csv"
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@vacaciones_bp.route("/reporte")
@role_required("admin", "rrhh")
def reporte():
    filters = _extract_reporte_filters(request.args)
    rows, totals = _build_reporte_vacaciones(filters)
    sectores = get_sectores(include_inactive=True)
    return render_template(
        "vacaciones/reporte.html",
        rows=rows,
        totals=totals,
        sectores=sectores,
        years=_current_year_options(),
        anio=filters["anio"],
        sector_id=filters["sector_id"],
        q=filters["search"],
        activo=filters["activo_raw"],
    )


@vacaciones_bp.route("/reporte/export.csv")
@role_required("admin", "rrhh")
def reporte_export_csv():
    filters = _extract_reporte_filters(request.args)
    rows, totals = _build_reporte_vacaciones(filters)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "empresa",
        "area",
        "puesto",
        "empleado",
        "dni",
        "legajo",
        "estado_empleado",
        "anio",
        "fecha_ingreso",
        "antiguedad_al_31_12",
        "dias_corresponden",
        "dias_compensatorios",
        "dias_tomados",
        "dias_pendientes_por_tomar",
        "solicitudes_pendientes",
        "dias_base",
        "dias_ajustes",
        "dias_disponibles_con_pendientes",
        "dias_trabajados_anio",
        "dias_habiles_anio",
        "calculo_proporcional",
        "error",
    ])
    for row in rows:
        writer.writerow([
            row.get("empresa_nombre") or "",
            row.get("sector_nombre") or "",
            row.get("puesto_nombre") or "",
            f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip(),
            row.get("dni") or "",
            row.get("legajo") or "",
            row.get("estado") or "",
            filters["anio"],
            row.get("fecha_ingreso") or "",
            row.get("antiguedad_al_31_12") or "",
            row.get("dias_corresponden") or 0,
            row.get("dias_compensatorios") or 0,
            row.get("dias_tomados") or 0,
            row.get("dias_pendientes_por_tomar") or 0,
            row.get("dias_pendientes") or 0,
            row.get("dias_base") or 0,
            row.get("dias_ajustes") or 0,
            row.get("dias_disponibles_con_pendientes") or 0,
            row.get("dias_trabajados_anio") or 0,
            row.get("dias_habiles_anio") or 0,
            "si" if row.get("calculo_proporcional") else "no",
            row.get("error") or "",
        ])

    writer.writerow([])
    writer.writerow(["Total empleados", totals["empleados"]])
    writer.writerow(["Con error", totals["con_error"]])
    writer.writerow(["Dias corresponden", totals["dias_corresponden"]])
    writer.writerow(["Dias compensatorios", totals["dias_compensatorios"]])
    writer.writerow(["Dias tomados", totals["dias_tomados"]])
    writer.writerow(["Dias pendientes por tomar", totals["dias_pendientes_por_tomar"]])
    writer.writerow(["Solicitudes pendientes", totals["dias_pendientes"]])
    writer.writerow(["Dias disponibles con pendientes", totals["dias_disponibles_con_pendientes"]])

    filename = f"vacaciones_reporte_{filters['anio']}_{datetime.date.today().isoformat()}.csv"
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@vacaciones_bp.route("/movimientos/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def movimiento_nuevo():
    empleados = get_empleados(include_inactive=True)
    tipo_default = (request.args.get("tipo") or "compensatorio").strip().lower()
    estado_default = (request.args.get("estado") or "aprobado").strip().lower()
    if tipo_default not in TIPOS_MOVIMIENTO:
        tipo_default = "compensatorio"
    if estado_default not in ESTADOS_MOVIMIENTO:
        estado_default = "aprobado"
    data = {
        "anio": datetime.date.today().year,
        "tipo": tipo_default,
        "estado": estado_default,
    }
    empleado_id = request.args.get("empleado_id", type=int)
    if empleado_id:
        data["empleado_id"] = empleado_id
    errors = []
    if request.method == "POST":
        data = _movimiento_form_data(request.form)
        try:
            movimiento_id = crear_movimiento_vacaciones_admin(data)
        except (VacacionesSaldoInsuficienteError, VacacionesError) as exc:
            errors.append(str(exc))
        else:
            log_audit(session, "create", "vacaciones_movimientos", movimiento_id)
            return redirect(url_for(
                "vacaciones.listado",
                empleado_id=data.get("empleado_id"),
                anio=data.get("anio"),
                msg="Movimiento registrado.",
            ))

    return render_template(
        "vacaciones/movimiento_form.html",
        mode="new",
        data=data,
        errors=errors,
        empleados=empleados,
        years=_current_year_options(),
    )


@vacaciones_bp.route("/movimientos/editar/<int:movimiento_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def movimiento_editar(movimiento_id):
    movimiento = get_movimiento_by_id(movimiento_id)
    if not movimiento:
        return redirect(url_for("vacaciones.listado", error="Movimiento no encontrado."))
    if str(movimiento.get("estado") or "").lower() != "pendiente":
        return redirect(url_for("vacaciones.listado", error="Solo se pueden editar movimientos pendientes."))

    empleados = get_empleados(include_inactive=True)
    data = dict(movimiento)
    errors = []
    if request.method == "POST":
        data = _movimiento_form_data(request.form)
        try:
            editar_movimiento_vacaciones_pendiente(movimiento_id, data)
        except (VacacionesSaldoInsuficienteError, VacacionesError) as exc:
            errors.append(str(exc))
        else:
            log_audit(session, "update", "vacaciones_movimientos", movimiento_id)
            return redirect(url_for(
                "vacaciones.listado",
                empleado_id=data.get("empleado_id"),
                anio=data.get("anio"),
                msg="Movimiento actualizado.",
            ))

    return render_template(
        "vacaciones/movimiento_form.html",
        mode="edit",
        data=data,
        errors=errors,
        empleados=empleados,
        years=_current_year_options(),
    )


@vacaciones_bp.route("/movimientos/aprobar/<int:movimiento_id>", methods=["POST"])
@role_required("admin", "rrhh")
def movimiento_aprobar(movimiento_id):
    try:
        aprobar_movimiento_vacaciones(movimiento_id, actor_id=session.get("user_id"))
    except (VacacionesSaldoInsuficienteError, VacacionesError) as exc:
        return redirect(url_for("vacaciones.listado", error=str(exc)))
    log_audit(session, "aprobar", "vacaciones_movimientos", movimiento_id)
    return redirect(url_for("vacaciones.listado", msg="Solicitud de vacaciones aprobada."))


@vacaciones_bp.route("/movimientos/rechazar/<int:movimiento_id>", methods=["POST"])
@role_required("admin", "rrhh")
def movimiento_rechazar(movimiento_id):
    motivo = (request.form.get("motivo") or "").strip()
    try:
        rechazar_movimiento_vacaciones(
            movimiento_id,
            actor_id=session.get("user_id"),
            motivo=motivo,
        )
    except VacacionesError as exc:
        return redirect(url_for("vacaciones.listado", error=str(exc)))
    log_audit(session, "rechazar", "vacaciones_movimientos", movimiento_id)
    return redirect(url_for("vacaciones.listado", msg="Solicitud de vacaciones rechazada."))


@vacaciones_bp.route("/movimientos/cancelar/<int:movimiento_id>", methods=["POST"])
@role_required("admin", "rrhh")
def movimiento_cancelar(movimiento_id):
    motivo = (request.form.get("motivo") or "").strip()
    try:
        ajuste_id = cancelar_movimiento_vacaciones(
            movimiento_id,
            actor_id=session.get("user_id"),
            motivo=motivo,
        )
    except VacacionesError as exc:
        return redirect(url_for("vacaciones.listado", error=str(exc)))
    log_audit(session, "cancel", "vacaciones_movimientos", movimiento_id)
    log_audit(session, "create", "vacaciones_movimientos", ajuste_id)
    return redirect(url_for("vacaciones.listado", msg="Movimiento revertido con ajuste."))


@vacaciones_bp.route("/compensatorios/carga-masiva", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def compensatorios_masivos():
    empleados = get_empleados(include_inactive=False)
    sectores = get_sectores(include_inactive=False)
    errors = []
    msg = None
    form_data = {
        "anio": datetime.date.today().year,
        "dias": "",
        "sector_id": None,
        "observacion": "",
    }

    if request.method == "POST":
        empleado_ids_raw = request.form.getlist("empleado_ids")
        empleado_ids = [int(x) for x in empleado_ids_raw if str(x).isdigit()]
        dias_raw = (request.form.get("dias") or "").strip()
        anio = int(request.form.get("anio") or datetime.date.today().year)
        observacion = (request.form.get("observacion") or "").strip() or None
        sector_id_raw = request.form.get("sector_id") or ""
        form_data.update({
            "anio": anio,
            "dias": dias_raw,
            "sector_id": int(sector_id_raw) if sector_id_raw.isdigit() else None,
            "observacion": observacion or "",
        })

        if not empleado_ids:
            errors.append("Seleccione al menos un empleado.")
        elif not dias_raw:
            errors.append("Ingrese la cantidad de días.")
        else:
            try:
                ok, errs = crear_compensatorios_bulk(
                    empleado_ids=empleado_ids,
                    dias=dias_raw,
                    anio=anio,
                    observacion=observacion,
                )
                if ok:
                    log_audit(session, "create", "vacaciones_movimientos", None)
                    msg = f"{ok} compensatorio(s) registrado(s) correctamente."
                errors.extend(e["error"] for e in errs)
            except VacacionesError as exc:
                errors.append(str(exc))

    return render_template(
        "vacaciones/compensatorios_masivo.html",
        empleados=empleados,
        sectores=sectores,
        years=_current_year_options(),
        form_data=form_data,
        errors=errors,
        msg=msg,
    )


@vacaciones_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    return redirect(url_for("vacaciones.movimiento_nuevo", tipo="tomado", estado="aprobado"))


@vacaciones_bp.route("/editar/<int:vacacion_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(vacacion_id):
    return redirect(url_for(
        "vacaciones.listado",
        error="Los periodos se gestionan desde movimientos de vacaciones.",
    ))


@vacaciones_bp.route("/eliminar/<int:vacacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar(vacacion_id):
    return redirect(url_for(
        "vacaciones.listado",
        error="Los periodos se revierten desde el movimiento aprobado; no se eliminan directo.",
    ))


# ---------------------------------------------------------------------------
# Gantt
# ---------------------------------------------------------------------------

def _to_str(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@vacaciones_bp.route("/gantt")
@role_required("admin", "rrhh")
def gantt():
    empleados_raw = get_empleados(include_inactive=False) or []
    empleados_json = [
        {"id": e["id"], "nombre": f"{e.get('apellido') or ''} {e.get('nombre') or ''}".strip()}
        for e in empleados_raw
    ]
    return render_template("vacaciones/gantt.html", empleados_json=empleados_json)


@vacaciones_bp.route("/gantt/api/datos")
@role_required("admin", "rrhh")
def gantt_api_datos():
    year = request.args.get("year", datetime.date.today().year, type=int)
    if year < 2000 or year > 2100:
        year = datetime.date.today().year

    rows = get_movimientos_gantt_year(year)

    movimientos = []
    for row in rows:
        movimientos.append({
            "id": row["id"],
            "empleado_id": row["empleado_id"],
            "empleado_nombre": f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip(),
            "tipo": row["tipo"],
            "estado": row["estado"],
            "dias": float(row["dias"] or 0),
            "fecha_desde": _to_str(row["fecha_desde"]),
            "fecha_hasta": _to_str(row["fecha_hasta"]),
            "observacion": row.get("observacion") or "",
        })

    return jsonify({"year": year, "movimientos": movimientos})


@vacaciones_bp.route("/gantt/api/movimientos", methods=["POST"])
@role_required("admin", "rrhh")
def gantt_api_crear():
    body = request.get_json(silent=True) or {}
    fecha_desde = str(body.get("fecha_desde") or "").strip()
    anio_raw = body.get("anio") or (fecha_desde[:4] if len(fecha_desde) >= 4 else "")
    try:
        anio = int(str(anio_raw)) if str(anio_raw).isdigit() else datetime.date.today().year
        data = {
            "empleado_id": body.get("empleado_id"),
            "anio": anio,
            "tipo": "tomado",
            "estado": "aprobado",
            "fecha_desde": fecha_desde or None,
            "fecha_hasta": str(body.get("fecha_hasta") or "").strip() or None,
            "observacion": str(body.get("observacion") or "").strip() or None,
            "dias": None,
        }
        movimiento_id = crear_movimiento_vacaciones_admin(data)
    except (VacacionesError, VacacionesSaldoInsuficienteError) as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(session, "create", "vacaciones_movimientos", movimiento_id)
    return jsonify({"ok": True, "id": movimiento_id}), 201


@vacaciones_bp.route("/gantt/api/movimientos/<int:movimiento_id>", methods=["PUT"])
@role_required("admin", "rrhh")
def gantt_api_editar(movimiento_id):
    body = request.get_json(silent=True) or {}
    fecha_desde = str(body.get("fecha_desde") or "").strip()
    anio_raw = body.get("anio") or (fecha_desde[:4] if len(fecha_desde) >= 4 else "")
    try:
        mov = get_movimiento_by_id(movimiento_id)
        if not mov:
            return jsonify({"error": "Movimiento no encontrado."}), 404
        anio = int(str(anio_raw)) if str(anio_raw).isdigit() else int(mov.get("anio") or datetime.date.today().year)
        estado_mov = str(mov.get("estado") or "").lower()
        data = {
            "empleado_id": body.get("empleado_id") or mov.get("empleado_id"),
            "anio": anio,
            "tipo": "tomado",
            "fecha_desde": fecha_desde or _to_str(mov.get("fecha_desde")),
            "fecha_hasta": str(body.get("fecha_hasta") or "").strip() or _to_str(mov.get("fecha_hasta")),
            "observacion": str(body.get("observacion") or "").strip() or None,
            "dias": None,
        }
        if estado_mov == "pendiente":
            editar_movimiento_vacaciones_pendiente(movimiento_id, data)
        elif estado_mov == "aprobado":
            editar_movimiento_vacaciones_aprobado(movimiento_id, data)
        else:
            return jsonify({"error": f"No se puede editar un movimiento en estado '{estado_mov}'."}), 400
    except (VacacionesError, VacacionesSaldoInsuficienteError) as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(session, "update", "vacaciones_movimientos", movimiento_id)
    return jsonify({"ok": True})


@vacaciones_bp.route("/gantt/api/movimientos/<int:movimiento_id>", methods=["DELETE"])
@role_required("admin", "rrhh")
def gantt_api_eliminar(movimiento_id):
    mov = get_movimiento_by_id(movimiento_id)
    if not mov:
        return jsonify({"error": "Movimiento no encontrado."}), 404
    estado = str(mov.get("estado") or "").lower()
    actor_id = session.get("user_id")
    try:
        if estado == "pendiente":
            rechazar_movimiento_vacaciones(
                movimiento_id,
                actor_id=actor_id,
                motivo="Eliminado desde Gantt",
            )
        elif estado == "aprobado":
            cancelar_movimiento_vacaciones(
                movimiento_id,
                actor_id=actor_id,
                motivo="Eliminado desde Gantt",
            )
        else:
            return jsonify({"error": f"No se puede eliminar un movimiento en estado '{estado}'."}), 400
    except VacacionesError as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(session, "delete", "vacaciones_movimientos", movimiento_id)
    return jsonify({"ok": True})
