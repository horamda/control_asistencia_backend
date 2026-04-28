import csv
import datetime
import io

from flask import Blueprint, Response, current_app, redirect, render_template, request, session, url_for

from repositories.empleado_repository import get_all as get_empleados
from repositories.pedido_mercaderia_repository import get_by_id, get_export, get_page, get_summary
from services.articulo_pedido_import_service import importar_articulos_desde_csv
from services.pedido_mercaderia_service import aprobar_pedido, rechazar_pedido
from utils.audit import log_audit
from web.auth.decorators import role_required

pedidos_mercaderia_bp = Blueprint(
    "pedidos_mercaderia",
    __name__,
    url_prefix="/pedidos-mercaderia",
)

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


@pedidos_mercaderia_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    filters, filter_error = _extract_filters(request.args)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    if not error:
        error = filter_error

    pedidos, total = get_page(
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
        "pedidos_mercaderia/listado.html",
        pedidos=pedidos,
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


@pedidos_mercaderia_bp.route("/<int:pedido_id>")
@role_required("admin", "rrhh")
def detalle(pedido_id):
    pedido = get_by_id(pedido_id)
    if not pedido:
        return redirect(url_for("pedidos_mercaderia.listado", error="Pedido no encontrado."))
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    items = pedido.pop("items", [])
    return render_template("pedidos_mercaderia/detalle.html", pedido=pedido, items=items, error=error, msg=msg)


@pedidos_mercaderia_bp.route("/export.csv")
@role_required("admin", "rrhh")
def export_csv():
    filters, error = _extract_filters(request.args)
    if error:
        return redirect(url_for("pedidos_mercaderia.listado", error=error))

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
            "pedido_id",
            "empresa",
            "dni",
            "apellido",
            "nombre",
            "periodo",
            "fecha_pedido",
            "estado",
            "codigo_articulo",
            "descripcion_articulo",
            "cantidad_bultos",
            "unidades_por_bulto",
            "resuelto_por",
            "resuelto_at",
            "motivo_rechazo",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("id"),
                row.get("empresa_nombre") or "",
                row.get("dni") or "",
                row.get("apellido") or "",
                row.get("nombre") or "",
                f"{int(row.get('periodo_year') or 0):04d}-{int(row.get('periodo_month') or 0):02d}",
                row.get("fecha_pedido") or "",
                row.get("estado") or "",
                row.get("codigo_articulo_snapshot") or "",
                row.get("descripcion_snapshot") or "",
                row.get("cantidad_bultos") or 0,
                row.get("unidades_por_bulto_snapshot") or 0,
                row.get("resuelto_by_usuario") or "",
                row.get("resuelto_at") or "",
                row.get("motivo_rechazo") or "",
            ]
        )

    csv_content = "\ufeff" + out.getvalue()
    filename = f"pedidos_mercaderia_{datetime.date.today().isoformat()}.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@pedidos_mercaderia_bp.route("/aprobar/<int:pedido_id>", methods=["POST"])
@role_required("admin", "rrhh")
def aprobar(pedido_id):
    origin = (request.form.get("origin") or "").strip()
    try:
        aprobar_pedido(pedido_id, actor_id=session.get("user_id"))
    except ValueError as exc:
        if origin == "detalle":
            return redirect(url_for("pedidos_mercaderia.detalle", pedido_id=pedido_id, error=str(exc)))
        return redirect(url_for("pedidos_mercaderia.listado", error=str(exc)))
    log_audit(session, "aprobar", "pedidos_mercaderia", pedido_id)
    if origin == "detalle":
        return redirect(url_for("pedidos_mercaderia.detalle", pedido_id=pedido_id, msg="Pedido aprobado."))
    return redirect(url_for("pedidos_mercaderia.listado", msg="Pedido aprobado."))


@pedidos_mercaderia_bp.route("/rechazar/<int:pedido_id>", methods=["POST"])
@role_required("admin", "rrhh")
def rechazar(pedido_id):
    motivo_rechazo = (request.form.get("motivo_rechazo") or "").strip() or None
    origin = (request.form.get("origin") or "").strip()
    try:
        rechazar_pedido(
            pedido_id,
            actor_id=session.get("user_id"),
            motivo_rechazo=motivo_rechazo,
        )
    except ValueError as exc:
        if origin == "detalle":
            return redirect(url_for("pedidos_mercaderia.detalle", pedido_id=pedido_id, error=str(exc)))
        return redirect(url_for("pedidos_mercaderia.listado", error=str(exc)))
    log_audit(session, "rechazar", "pedidos_mercaderia", pedido_id)
    if origin == "detalle":
        return redirect(url_for("pedidos_mercaderia.detalle", pedido_id=pedido_id, msg="Pedido rechazado."))
    return redirect(url_for("pedidos_mercaderia.listado", msg="Pedido rechazado."))


@pedidos_mercaderia_bp.route("/articulos/importar-csv", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def importar_csv():
    resultado = None

    if request.method == "POST":
        archivo = request.files.get("archivo_csv")
        if not archivo or not str(archivo.filename or "").lower().endswith(".csv"):
            resultado = {"error": "Debe subir un archivo .csv valido."}
        else:
            try:
                resultado = importar_articulos_desde_csv(archivo.stream)
                log_audit(session, "importar_csv", "articulos_catalogo_pedidos", 0)
            except Exception as exc:
                current_app.logger.exception("importar_articulos_catalogo_error")
                resultado = {"error": f"Error al procesar el archivo: {exc}"}

    return render_template(
        "pedidos_mercaderia/importar_csv.html",
        resultado=resultado,
    )
