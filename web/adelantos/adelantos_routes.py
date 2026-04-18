import csv
import datetime
import io

from flask import Blueprint, Response, redirect, render_template, request, session, url_for

from repositories.adelanto_repository import get_export, get_page, get_summary
from repositories.empleado_repository import get_all as get_empleados
from services.adelanto_service import aprobar_adelanto, rechazar_adelanto
from utils.audit import log_audit
from web.auth.decorators import role_required

adelantos_bp = Blueprint("adelantos", __name__, url_prefix="/adelantos")

ESTADOS_VALIDOS = {"pendiente", "aprobado", "rechazado", "cancelado"}


def _current_year_options():
    current_year = datetime.date.today().year
    return list(range(current_year, current_year - 4, -1))


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
        "search": (args.get("q") or "").strip() or None,
        "estado": (args.get("estado") or "").strip().lower() or None,
        "periodo_year": args.get("anio", type=int),
        "periodo_month": args.get("mes", type=int),
    }
    error = None
    if filters["estado"] and filters["estado"] not in ESTADOS_VALIDOS:
        error = "Estado invalido."
        filters["estado"] = None
    if filters["periodo_month"] is not None and filters["periodo_month"] not in range(1, 13):
        error = "Mes invalido."
        filters["periodo_month"] = None
    return filters, error


@adelantos_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    filters, filter_error = _extract_filters(request.args)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    if not error:
        error = filter_error

    adelantos, total = get_page(
        page=filters["page"],
        per_page=filters["per_page"],
        empleado_id=filters["empleado_id"],
        search=filters["search"],
        estado=filters["estado"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )
    summary = get_summary(
        empleado_id=filters["empleado_id"],
        search=filters["search"],
        estado=filters["estado"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )
    empleados = get_empleados(include_inactive=True)

    return render_template(
        "adelantos/listado.html",
        adelantos=adelantos,
        total=total,
        summary=summary,
        empleados=empleados,
        page=filters["page"],
        per_page=filters["per_page"],
        empleado_id=filters["empleado_id"],
        q=filters["search"],
        estado=filters["estado"],
        anio=filters["periodo_year"],
        mes=filters["periodo_month"],
        years=_current_year_options(),
        months=_month_options(),
        error=error,
        msg=msg,
    )


@adelantos_bp.route("/export.csv")
@role_required("admin", "rrhh")
def export_csv():
    filters, error = _extract_filters(request.args)
    if error:
        return redirect(url_for("adelantos.listado", error=error))

    rows = get_export(
        empleado_id=filters["empleado_id"],
        search=filters["search"],
        estado=filters["estado"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
        limit=10000,
    )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "id",
            "empresa",
            "empleado",
            "dni",
            "periodo",
            "fecha_solicitud",
            "estado",
            "resuelto_por",
            "resuelto_at",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("id"),
                row.get("empresa_nombre") or "",
                f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip(),
                row.get("dni") or "",
                f"{int(row.get('periodo_year') or 0):04d}-{int(row.get('periodo_month') or 0):02d}",
                row.get("fecha_solicitud") or "",
                row.get("estado") or "",
                row.get("resuelto_by_usuario") or "",
                row.get("resuelto_at") or "",
                row.get("created_at") or "",
            ]
        )

    csv_content = "\ufeff" + out.getvalue()
    filename = f"adelantos_{datetime.date.today().isoformat()}.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@adelantos_bp.route("/aprobar/<int:adelanto_id>", methods=["POST"])
@role_required("admin", "rrhh")
def aprobar(adelanto_id):
    try:
        aprobar_adelanto(adelanto_id, actor_id=session.get("user_id"))
    except ValueError as exc:
        return redirect(url_for("adelantos.listado", error=str(exc)))
    log_audit(session, "aprobar", "adelantos", adelanto_id)
    return redirect(url_for("adelantos.listado", msg="Adelanto aprobado."))


@adelantos_bp.route("/rechazar/<int:adelanto_id>", methods=["POST"])
@role_required("admin", "rrhh")
def rechazar(adelanto_id):
    try:
        rechazar_adelanto(adelanto_id, actor_id=session.get("user_id"))
    except ValueError as exc:
        return redirect(url_for("adelantos.listado", error=str(exc)))
    log_audit(session, "rechazar", "adelantos", adelanto_id)
    return redirect(url_for("adelantos.listado", msg="Adelanto rechazado."))
