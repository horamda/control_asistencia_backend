import csv
import datetime
import io

from flask import Blueprint, Response, abort, redirect, render_template, request, session, url_for

from repositories.empleado_repository import get_all as get_empleados
from repositories.vacacion_repository import create, delete, get_all, get_by_id, update
from repositories.vacaciones_repository import (
    get_movimientos_export,
    get_movimientos_page,
    get_movimientos_summary,
)
from services.vacaciones_service import (
    VacacionesError,
    VacacionesSaldoInsuficienteError,
    aprobar_movimiento_vacaciones,
    calcular_resumen_vacaciones,
    crear_movimiento_vacaciones_admin,
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


def _extract_filters(args):
    filters = {
        "page": args.get("page", 1, type=int) or 1,
        "per_page": args.get("per", 20, type=int) or 20,
        "empleado_id": args.get("empleado_id", type=int),
        "search": (args.get("q") or "").strip() or None,
        "estado": (args.get("estado") or "").strip().lower() or None,
        "tipo": (args.get("tipo") or "").strip().lower() or None,
        "anio": args.get("anio", type=int) or datetime.date.today().year,
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
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
    )
    summary = get_movimientos_summary(
        empleado_id=filters["empleado_id"],
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
    )
    empleados = get_empleados(include_inactive=True)
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
        saldo=saldo,
        page=filters["page"],
        per_page=filters["per_page"],
        empleado_id=filters["empleado_id"],
        q=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        years=_current_year_options(),
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
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        limit=10000,
    )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "id",
        "empresa",
        "empleado",
        "dni",
        "anio",
        "tipo",
        "dias",
        "estado",
        "fecha_desde",
        "fecha_hasta",
        "observacion",
        "created_at",
    ])
    for row in rows:
        writer.writerow([
            row.get("id"),
            row.get("empresa_nombre") or "",
            f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip(),
            row.get("dni") or "",
            row.get("anio") or "",
            row.get("tipo") or "",
            row.get("dias") or "",
            row.get("estado") or "",
            row.get("fecha_desde") or "",
            row.get("fecha_hasta") or "",
            row.get("observacion") or "",
            row.get("created_at") or "",
        ])

    filename = f"vacaciones_movimientos_{datetime.date.today().isoformat()}.csv"
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@vacaciones_bp.route("/movimientos/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def movimiento_nuevo():
    empleados = get_empleados(include_inactive=True)
    data = {
        "anio": datetime.date.today().year,
        "tipo": "compensatorio",
        "estado": "aprobado",
    }
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
    try:
        rechazar_movimiento_vacaciones(movimiento_id, actor_id=session.get("user_id"))
    except VacacionesError as exc:
        return redirect(url_for("vacaciones.listado", error=str(exc)))
    log_audit(session, "rechazar", "vacaciones_movimientos", movimiento_id)
    return redirect(url_for("vacaciones.listado", msg="Solicitud de vacaciones rechazada."))


@vacaciones_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        if errors:
            return render_template("vacaciones/form.html", mode="new", data=data, errors=errors, empleados=empleados)
        vac_id = create(data)
        log_audit(session, "create", "vacaciones", vac_id)
        return redirect(url_for("vacaciones.listado"))

    return render_template("vacaciones/form.html", mode="new", data={}, empleados=empleados)


@vacaciones_bp.route("/editar/<int:vacacion_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(vacacion_id):
    vacacion = get_by_id(vacacion_id)
    if not vacacion:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        if errors:
            merged = dict(vacacion)
            merged.update(data)
            return render_template("vacaciones/form.html", mode="edit", data=merged, errors=errors, empleados=empleados)
        update(vacacion_id, data)
        log_audit(session, "update", "vacaciones", vacacion_id)
        return redirect(url_for("vacaciones.listado"))

    return render_template("vacaciones/form.html", mode="edit", data=vacacion, empleados=empleados)


@vacaciones_bp.route("/eliminar/<int:vacacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar(vacacion_id):
    delete(vacacion_id)
    log_audit(session, "delete", "vacaciones", vacacion_id)
    return redirect(url_for("vacaciones.listado"))
