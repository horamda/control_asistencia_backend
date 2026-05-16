from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.empleado_repository import get_all as get_empleados
from repositories.empresa_repository import get_all as get_empresas
from repositories.sector_repository import (
    create,
    get_all as get_sectores,
    get_by_id,
    get_page,
    set_activo,
    update,
    would_create_cycle,
)
from utils.audit import log_audit

sectores_bp = Blueprint("sectores", __name__, url_prefix="/sectores")


def _parse_int(value):
    raw = str(value or "").strip()
    return int(raw) if raw.isdigit() else None


def _extract(form):
    return {
        "empresa_id": _parse_int(form.get("empresa_id")),
        "sector_padre_id": _parse_int(form.get("sector_padre_id")),
        "responsable_empleado_id": _parse_int(form.get("responsable_empleado_id")),
        "nombre": (form.get("nombre") or "").strip(),
        "activo": form.get("activo") == "1"
    }


def _find_by_id(rows, row_id):
    if not row_id:
        return None
    return next((row for row in rows if int(row.get("id") or 0) == int(row_id)), None)


def _validate(form, *, sector_id=None, sectores=None, empleados=None):
    errors = []
    data = _extract(form)
    sectores = sectores or []
    empleados = empleados or []

    empresa_id = data.get("empresa_id")
    sector_padre_id = data.get("sector_padre_id")
    responsable_id = data.get("responsable_empleado_id")

    if not empresa_id:
        errors.append("Empresa es requerida.")
    if not (form.get("nombre") or "").strip():
        errors.append("Nombre es requerido.")

    if sector_padre_id:
        sector_padre = _find_by_id(sectores, sector_padre_id)
        if not sector_padre:
            errors.append("Sector superior invalido.")
        elif empresa_id and int(sector_padre.get("empresa_id") or 0) != int(empresa_id):
            errors.append("El sector superior debe pertenecer a la misma empresa.")
        elif sector_id and int(sector_padre_id) == int(sector_id):
            errors.append("Un sector no puede ser superior de si mismo.")
        elif sector_id and would_create_cycle(int(sector_id), int(sector_padre_id)):
            errors.append("La jerarquia seleccionada genera un ciclo.")

    if responsable_id:
        responsable = _find_by_id(empleados, responsable_id)
        if not responsable:
            errors.append("Responsable invalido.")
        elif empresa_id and int(responsable.get("empresa_id") or 0) != int(empresa_id):
            errors.append("El responsable debe pertenecer a la misma empresa.")

    return errors


def _catalogos():
    return {
        "empresas": get_empresas(include_inactive=True),
        "sectores_padre": get_sectores(include_inactive=True),
        "empleados_responsables": get_empleados(include_inactive=True),
    }


@sectores_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empresa_id = request.args.get("empresa_id", type=int)
    activo = request.args.get("activo", default=None, type=int)
    search = request.args.get("q")
    sectores, total = get_page(page, per_page, empresa_id, search, activo)
    empresas = get_empresas(include_inactive=True)
    return render_template(
        "sectores/listado.html",
        sectores=sectores,
        empresas=empresas,
        empresa_id=empresa_id,
        activo=activo,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@sectores_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    catalogos = _catalogos()
    if request.method == "POST":
        errors = _validate(
            request.form,
            sectores=catalogos["sectores_padre"],
            empleados=catalogos["empleados_responsables"],
        )
        data = _extract(request.form)
        if errors:
            return render_template("sectores/form.html", mode="new", data=data, errors=errors, **catalogos)
        sec_id = create(data)
        log_audit(session, "create", "sectores", sec_id)
        return redirect(url_for("sectores.listado"))

    return render_template("sectores/form.html", mode="new", data={}, **catalogos)


@sectores_bp.route("/editar/<int:sector_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(sector_id):
    sector = get_by_id(sector_id)
    if not sector:
        abort(404)

    catalogos = _catalogos()
    if request.method == "POST":
        errors = _validate(
            request.form,
            sector_id=sector_id,
            sectores=catalogos["sectores_padre"],
            empleados=catalogos["empleados_responsables"],
        )
        data = _extract(request.form)
        if errors:
            merged = dict(sector)
            merged.update(data)
            return render_template("sectores/form.html", mode="edit", data=merged, errors=errors, **catalogos)
        update(sector_id, data)
        log_audit(session, "update", "sectores", sector_id)
        return redirect(url_for("sectores.listado"))

    return render_template("sectores/form.html", mode="edit", data=sector, **catalogos)


@sectores_bp.route("/activar/<int:sector_id>")
@role_required("admin")
def activar(sector_id):
    set_activo(sector_id, 1)
    log_audit(session, "activate", "sectores", sector_id)
    return redirect(url_for("sectores.listado"))


@sectores_bp.route("/desactivar/<int:sector_id>")
@role_required("admin")
def desactivar(sector_id):
    set_activo(sector_id, 0)
    log_audit(session, "deactivate", "sectores", sector_id)
    return redirect(url_for("sectores.listado"))
