import csv
import datetime
import io

from flask import Blueprint, Response, current_app, redirect, render_template, request, session, url_for

from repositories.empleado_repository import get_all as get_empleados
from repositories.empresa_repository import get_all as get_empresas
from repositories.premio_concurso_repository import (
    create_concurso,
    delete_resultado,
    get_concurso_by_id,
    get_concursos_for_empresa,
    get_concursos_page,
    get_resultado_by_id,
    get_resultados_export,
    get_resultados_page,
    get_resultados_summary,
    save_resultado,
    set_concurso_activo,
    update_concurso,
)
from repositories.sector_repository import get_page as get_sectores_page
from services.premio_concurso_import_service import PremioImportError, importar_premios_desde_archivo
from services.export_excel_service import generar_premios_concursos_resultados_excel
from utils.audit import log_audit
from web.auth.decorators import role_required

premios_concursos_bp = Blueprint(
    "premios_concursos",
    __name__,
    url_prefix="/premios-concursos",
)

_ALCANCES = {"sector", "global"}


def _current_year_options():
    current_year = datetime.date.today().year
    return list(range(current_year + 1, current_year - 4, -1))


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


def _get_sectores(empresa_id: int | None, *, include_inactive: bool = False):
    if not empresa_id:
        return []
    activo = None if include_inactive else 1
    rows, _ = get_sectores_page(1, 1000, empresa_id=empresa_id, activo=activo)
    return rows


def _parse_activo(value):
    raw = str(value or "all").strip().lower()
    if raw == "1":
        return 1, "1"
    if raw == "0":
        return 0, "0"
    return None, "all"


def _extract_concurso_filters(args):
    activo, activo_raw = _parse_activo(args.get("activo"))
    alcance = (args.get("alcance") or "").strip().lower() or None
    error = None
    if alcance and alcance not in _ALCANCES:
        error = "Alcance invalido."
        alcance = None
    return {
        "page": args.get("page", 1, type=int) or 1,
        "per_page": args.get("per", 20, type=int) or 20,
        "empresa_id": args.get("empresa_id", type=int),
        "sector_id": args.get("sector_id", type=int),
        "search": (args.get("q") or "").strip() or None,
        "activo": activo,
        "activo_raw": activo_raw,
        "alcance": alcance,
    }, error


def _extract_concurso_form(form):
    alcance = (form.get("alcance") or "sector").strip().lower()
    return {
        "empresa_id": form.get("empresa_id", type=int),
        "sector_id": form.get("sector_id", type=int),
        "codigo": (form.get("codigo") or "").strip().upper(),
        "nombre": (form.get("nombre") or "").strip(),
        "descripcion": (form.get("descripcion") or "").strip() or None,
        "alcance": alcance,
        "activo": form.get("activo") == "1",
    }


def _validate_concurso(data: dict) -> list[str]:
    errors = []
    if not data.get("empresa_id"):
        errors.append("Empresa es obligatoria.")
    if data.get("alcance") not in _ALCANCES:
        errors.append("Alcance invalido.")
    if data.get("alcance") == "sector" and not data.get("sector_id"):
        errors.append("Sector es obligatorio para concursos sectoriales.")
    if data.get("alcance") == "global":
        data["sector_id"] = None
    if not data.get("codigo"):
        errors.append("Codigo es obligatorio.")
    if not data.get("nombre"):
        errors.append("Nombre es obligatorio.")
    return errors


@premios_concursos_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    filters, filter_error = _extract_concurso_filters(request.args)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    if not error:
        error = filter_error

    concursos, total = get_concursos_page(
        page=filters["page"],
        per_page=filters["per_page"],
        empresa_id=filters["empresa_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        activo=filters["activo"],
        alcance=filters["alcance"],
    )
    empresas = get_empresas(include_inactive=True)
    sectores = _get_sectores(filters["empresa_id"], include_inactive=True)

    return render_template(
        "premios_concursos/listado.html",
        concursos=concursos,
        total=total,
        empresas=empresas,
        sectores=sectores,
        page=filters["page"],
        per_page=filters["per_page"],
        empresa_id=filters["empresa_id"],
        sector_id=filters["sector_id"],
        q=filters["search"],
        activo=filters["activo_raw"],
        alcance=filters["alcance"],
        error=error,
        msg=msg,
    )


@premios_concursos_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    empresas = get_empresas(include_inactive=True)
    empresa_id = request.args.get("empresa_id", type=int) or request.form.get("empresa_id", type=int)
    data = {
        "empresa_id": empresa_id,
        "alcance": "sector",
        "activo": True,
    }
    error = None

    if request.method == "POST":
        data = _extract_concurso_form(request.form)
        errors = _validate_concurso(data)
        if errors:
            error = " ".join(errors)
        else:
            try:
                concurso_id = create_concurso(data)
                log_audit(session, "crear", "premios_concursos", concurso_id)
                return redirect(url_for("premios_concursos.listado", empresa_id=data["empresa_id"], msg="Concurso creado."))
            except Exception as exc:
                current_app.logger.exception("premio_concurso_create_error")
                if "Duplicate entry" in str(exc):
                    error = "Ya existe un concurso con ese codigo en la empresa."
                else:
                    error = "Error al guardar el concurso."

    sectores = _get_sectores(data.get("empresa_id"), include_inactive=True)
    return render_template(
        "premios_concursos/form.html",
        concurso=None,
        data=data,
        empresas=empresas,
        sectores=sectores,
        error=error,
    )


@premios_concursos_bp.route("/<int:concurso_id>/editar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(concurso_id):
    concurso = get_concurso_by_id(concurso_id)
    if not concurso:
        return redirect(url_for("premios_concursos.listado", error="Concurso no encontrado."))

    empresas = get_empresas(include_inactive=True)
    data = dict(concurso)
    error = None

    if request.method == "POST":
        data = _extract_concurso_form(request.form)
        errors = _validate_concurso(data)
        if errors:
            error = " ".join(errors)
        else:
            try:
                update_concurso(concurso_id, data)
                log_audit(session, "editar", "premios_concursos", concurso_id)
                return redirect(url_for("premios_concursos.listado", empresa_id=data["empresa_id"], msg="Concurso actualizado."))
            except Exception as exc:
                current_app.logger.exception("premio_concurso_update_error")
                if "Duplicate entry" in str(exc):
                    error = "Ya existe un concurso con ese codigo en la empresa."
                else:
                    error = "Error al actualizar el concurso."

    sectores = _get_sectores(data.get("empresa_id"), include_inactive=True)
    return render_template(
        "premios_concursos/form.html",
        concurso=concurso,
        data=data,
        empresas=empresas,
        sectores=sectores,
        error=error,
    )


@premios_concursos_bp.route("/<int:concurso_id>/activar", methods=["POST"])
@role_required("admin", "rrhh")
def activar(concurso_id):
    concurso = get_concurso_by_id(concurso_id)
    if not concurso:
        return redirect(url_for("premios_concursos.listado", error="Concurso no encontrado."))
    set_concurso_activo(concurso_id, 1)
    log_audit(session, "activar", "premios_concursos", concurso_id)
    return redirect(url_for("premios_concursos.listado", empresa_id=concurso["empresa_id"], msg="Concurso activado."))


@premios_concursos_bp.route("/<int:concurso_id>/desactivar", methods=["POST"])
@role_required("admin", "rrhh")
def desactivar(concurso_id):
    concurso = get_concurso_by_id(concurso_id)
    if not concurso:
        return redirect(url_for("premios_concursos.listado", error="Concurso no encontrado."))
    set_concurso_activo(concurso_id, 0)
    log_audit(session, "desactivar", "premios_concursos", concurso_id)
    return redirect(url_for("premios_concursos.listado", empresa_id=concurso["empresa_id"], msg="Concurso desactivado."))


def _extract_resultado_filters(args):
    filters = {
        "page": args.get("page", 1, type=int) or 1,
        "per_page": args.get("per", 20, type=int) or 20,
        "empresa_id": args.get("empresa_id", type=int),
        "sector_id": args.get("sector_id", type=int),
        "empleado_id": args.get("empleado_id", type=int),
        "concurso_id": args.get("concurso_id", type=int),
        "periodo_year": args.get("anio", type=int),
        "periodo_month": args.get("mes", type=int),
        "search": (args.get("q") or "").strip() or None,
    }
    error = None
    if filters["periodo_month"] is not None and filters["periodo_month"] not in range(1, 13):
        error = "Mes invalido."
        filters["periodo_month"] = None
    return filters, error


@premios_concursos_bp.route("/resultados")
@role_required("admin", "rrhh")
def resultados():
    filters, filter_error = _extract_resultado_filters(request.args)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    if not error:
        error = filter_error

    rows, total = get_resultados_page(
        page=filters["page"],
        per_page=filters["per_page"],
        empresa_id=filters["empresa_id"],
        empleado_id=filters["empleado_id"],
        concurso_id=filters["concurso_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )
    summary = get_resultados_summary(
        empresa_id=filters["empresa_id"],
        empleado_id=filters["empleado_id"],
        concurso_id=filters["concurso_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )

    empresas = get_empresas(include_inactive=True)
    sectores = _get_sectores(filters["empresa_id"], include_inactive=True)
    concursos = get_concursos_for_empresa(filters["empresa_id"], activo=None) if filters["empresa_id"] else []
    empleados = get_empleados(include_inactive=True)

    return render_template(
        "premios_concursos/resultados.html",
        resultados=rows,
        total=total,
        summary=summary,
        empresas=empresas,
        sectores=sectores,
        concursos=concursos,
        empleados=empleados,
        years=_current_year_options(),
        months=_month_options(),
        page=filters["page"],
        per_page=filters["per_page"],
        empresa_id=filters["empresa_id"],
        sector_id=filters["sector_id"],
        empleado_id=filters["empleado_id"],
        concurso_id=filters["concurso_id"],
        anio=filters["periodo_year"],
        mes=filters["periodo_month"],
        q=filters["search"],
        error=error,
        msg=msg,
    )


def _extract_resultado_form(form):
    return {
        "empresa_id": form.get("empresa_id", type=int),
        "empleado_id": form.get("empleado_id", type=int),
        "concurso_id": form.get("concurso_id", type=int),
        "periodo": (form.get("periodo") or "").strip(),
        "ranking": form.get("ranking", type=int),
        "observaciones": (form.get("observaciones") or "").strip() or None,
        "actor_id": session.get("user_id"),
    }


def _validate_resultado_form(data: dict) -> list[str]:
    errors = []
    if not data.get("empresa_id"):
        errors.append("Empresa es obligatoria.")
    if not data.get("empleado_id"):
        errors.append("Empleado es obligatorio.")
    if not data.get("concurso_id"):
        errors.append("Concurso es obligatorio.")
    if not data.get("periodo"):
        errors.append("Periodo es obligatorio.")
    if not data.get("ranking") or int(data.get("ranking") or 0) < 1:
        errors.append("Ranking debe ser mayor o igual a 1.")
    return errors


def _render_resultado_form(*, resultado=None, data=None, error=None):
    data = data or {}
    empresa_id = data.get("empresa_id") or (resultado or {}).get("empresa_id")
    return render_template(
        "premios_concursos/resultado_form.html",
        resultado=resultado,
        data=data,
        empresas=get_empresas(include_inactive=True),
        sectores=_get_sectores(empresa_id, include_inactive=True),
        concursos=get_concursos_for_empresa(empresa_id, activo=1) if empresa_id else [],
        empleados=get_empleados(include_inactive=True),
        error=error,
    )


@premios_concursos_bp.route("/resultados/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def resultado_nuevo():
    data = {
        "empresa_id": request.args.get("empresa_id", type=int),
        "periodo": f"{datetime.date.today().year:04d}-{datetime.date.today().month:02d}",
    }
    error = None
    if request.method == "POST":
        data = _extract_resultado_form(request.form)
        errors = _validate_resultado_form(data)
        if errors:
            error = " ".join(errors)
        else:
            try:
                resultado_id, _ = save_resultado(data)
                log_audit(session, "crear", "premios_resultados", resultado_id)
                return redirect(url_for("premios_concursos.resultados", empresa_id=data["empresa_id"], msg="Resultado guardado."))
            except ValueError as exc:
                error = str(exc)
            except Exception:
                current_app.logger.exception("premio_resultado_create_error")
                error = "Error al guardar el resultado."
    return _render_resultado_form(data=data, error=error)


@premios_concursos_bp.route("/resultados/<int:resultado_id>/editar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def resultado_editar(resultado_id):
    resultado = get_resultado_by_id(resultado_id)
    if not resultado:
        return redirect(url_for("premios_concursos.resultados", error="Resultado no encontrado."))
    data = dict(resultado)
    data["periodo"] = resultado.get("periodo_label")
    error = None

    if request.method == "POST":
        data = _extract_resultado_form(request.form)
        errors = _validate_resultado_form(data)
        if errors:
            error = " ".join(errors)
        else:
            try:
                save_resultado(data, resultado_id=resultado_id)
                log_audit(session, "editar", "premios_resultados", resultado_id)
                return redirect(url_for("premios_concursos.resultados", empresa_id=data["empresa_id"], msg="Resultado actualizado."))
            except ValueError as exc:
                error = str(exc)
            except Exception:
                current_app.logger.exception("premio_resultado_update_error")
                error = "Error al actualizar el resultado."

    return _render_resultado_form(resultado=resultado, data=data, error=error)


@premios_concursos_bp.route("/resultados/<int:resultado_id>/eliminar", methods=["POST"])
@role_required("admin", "rrhh")
def resultado_eliminar(resultado_id):
    resultado = get_resultado_by_id(resultado_id)
    if not resultado:
        return redirect(url_for("premios_concursos.resultados", error="Resultado no encontrado."))
    delete_resultado(resultado_id)
    log_audit(session, "eliminar", "premios_resultados", resultado_id)
    return redirect(url_for("premios_concursos.resultados", empresa_id=resultado["empresa_id"], msg="Resultado eliminado."))


@premios_concursos_bp.route("/resultados/export.csv")
@role_required("admin", "rrhh")
def resultados_export_csv():
    filters, error = _extract_resultado_filters(request.args)
    if error:
        return redirect(url_for("premios_concursos.resultados", error=error))
    rows = get_resultados_export(
        empresa_id=filters["empresa_id"],
        empleado_id=filters["empleado_id"],
        concurso_id=filters["concurso_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "id",
        "empresa",
        "periodo",
        "legajo",
        "dni",
        "apellido",
        "nombre",
        "codigo_concurso",
        "concurso",
        "alcance",
        "sector",
        "ranking",
        "observaciones",
    ])
    for row in rows:
        writer.writerow([
            row.get("id"),
            row.get("empresa_nombre") or "",
            row.get("periodo_label") or "",
            row.get("legajo") or row.get("legajo_snapshot") or "",
            row.get("dni") or "",
            row.get("apellido") or "",
            row.get("nombre") or "",
            row.get("concurso_codigo") or row.get("concurso_codigo_snapshot") or "",
            row.get("concurso_nombre") or row.get("concurso_nombre_snapshot") or "",
            row.get("concurso_alcance") or "",
            row.get("sector_nombre") or "",
            row.get("ranking") or "",
            row.get("observaciones") or "",
        ])
    csv_content = "\ufeff" + out.getvalue()
    filename = f"premios_resultados_{datetime.date.today().isoformat()}.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@premios_concursos_bp.route("/resultados/export.xlsx")
@role_required("admin", "rrhh")
def resultados_export_xlsx():
    filters, error = _extract_resultado_filters(request.args)
    if error:
        return redirect(url_for("premios_concursos.resultados", error=error))

    rows = get_resultados_export(
        empresa_id=filters["empresa_id"],
        empleado_id=filters["empleado_id"],
        concurso_id=filters["concurso_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )
    summary = get_resultados_summary(
        empresa_id=filters["empresa_id"],
        empleado_id=filters["empleado_id"],
        concurso_id=filters["concurso_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        periodo_year=filters["periodo_year"],
        periodo_month=filters["periodo_month"],
    )

    empresas = get_empresas(include_inactive=True)
    sectores = _get_sectores(filters["empresa_id"], include_inactive=True)
    concursos = get_concursos_for_empresa(filters["empresa_id"], activo=None) if filters["empresa_id"] else []
    empleados = get_empleados(include_inactive=True)

    workbook = generar_premios_concursos_resultados_excel(
        rows=rows,
        summary=summary,
        filters={
            "empresa_label": next((e.get("razon_social") for e in empresas if int(e.get("id") or 0) == int(filters["empresa_id"] or 0)), None),
            "sector_label": next((s.get("nombre") for s in sectores if int(s.get("id") or 0) == int(filters["sector_id"] or 0)), None),
            "empleado_label": next(
                (
                    f"{e.get('apellido') or ''} {e.get('nombre') or ''}".strip()
                    for e in empleados
                    if int(e.get("id") or 0) == int(filters["empleado_id"] or 0)
                ),
                None,
            ),
            "concurso_label": next(
                (
                    f"{c.get('codigo') or ''} - {c.get('nombre') or ''}".strip(" -")
                    for c in concursos
                    if int(c.get("id") or 0) == int(filters["concurso_id"] or 0)
                ),
                None,
            ),
            "periodo_year": filters["periodo_year"],
            "periodo_month": filters["periodo_month"],
            "search": filters["search"],
        },
    )
    filename = f"premios_resultados_{datetime.date.today().isoformat()}.xlsx"
    return current_app.response_class(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@premios_concursos_bp.route("/resultados/importar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def resultados_importar():
    empresas = get_empresas(include_inactive=True)
    resultado = None
    if request.method == "POST":
        empresa_id = request.form.get("empresa_id", type=int)
        archivo = request.files.get("archivo")
        filename = str((archivo.filename if archivo else "") or "")
        if not empresa_id:
            resultado = {"error": "Debe seleccionar una empresa."}
        elif not archivo or not filename.lower().endswith((".csv", ".xlsx")):
            resultado = {"error": "Debe subir un archivo .csv o .xlsx valido."}
        else:
            try:
                resultado = importar_premios_desde_archivo(
                    empresa_id,
                    archivo.stream,
                    filename,
                    actor_id=session.get("user_id"),
                )
                log_audit(session, "importar", "premios_resultados", 0)
            except PremioImportError as exc:
                resultado = {"error": str(exc)}
            except Exception as exc:
                current_app.logger.exception("premios_resultados_import_error")
                resultado = {"error": f"Error al procesar el archivo: {exc}"}
    return render_template("premios_concursos/importar.html", empresas=empresas, resultado=resultado)
