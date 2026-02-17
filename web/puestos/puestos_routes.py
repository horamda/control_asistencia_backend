from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.puesto_repository import get_page, get_by_id, create, update, set_activo
from repositories.empresa_repository import get_all as get_empresas
from utils.audit import log_audit

puestos_bp = Blueprint("puestos", __name__, url_prefix="/puestos")


def _extract(form):
    return {
        "empresa_id": int(form.get("empresa_id")) if form.get("empresa_id") and form.get("empresa_id").isdigit() else None,
        "nombre": (form.get("nombre") or "").strip(),
        "activo": form.get("activo") == "1"
    }


def _validate(form):
    errors = []
    if not (form.get("empresa_id") or "").isdigit():
        errors.append("Empresa es requerida.")
    if not (form.get("nombre") or "").strip():
        errors.append("Nombre es requerido.")
    return errors


@puestos_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empresa_id = request.args.get("empresa_id", type=int)
    activo = request.args.get("activo", default=None, type=int)
    search = request.args.get("q")
    puestos, total = get_page(page, per_page, empresa_id, search, activo)
    empresas = get_empresas(include_inactive=True)
    return render_template(
        "puestos/listado.html",
        puestos=puestos,
        empresas=empresas,
        empresa_id=empresa_id,
        activo=activo,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@puestos_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empresas = get_empresas(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        if errors:
            return render_template("puestos/form.html", mode="new", data=data, errors=errors, empresas=empresas)
        puesto_id = create(data)
        log_audit(session, "create", "puestos", puesto_id)
        return redirect(url_for("puestos.listado"))

    return render_template("puestos/form.html", mode="new", data={}, empresas=empresas)


@puestos_bp.route("/editar/<int:puesto_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(puesto_id):
    puesto = get_by_id(puesto_id)
    if not puesto:
        abort(404)

    empresas = get_empresas(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        if errors:
            merged = dict(puesto)
            merged.update(data)
            return render_template("puestos/form.html", mode="edit", data=merged, errors=errors, empresas=empresas)
        update(puesto_id, data)
        log_audit(session, "update", "puestos", puesto_id)
        return redirect(url_for("puestos.listado"))

    return render_template("puestos/form.html", mode="edit", data=puesto, empresas=empresas)


@puestos_bp.route("/activar/<int:puesto_id>")
@role_required("admin")
def activar(puesto_id):
    set_activo(puesto_id, 1)
    log_audit(session, "activate", "puestos", puesto_id)
    return redirect(url_for("puestos.listado"))


@puestos_bp.route("/desactivar/<int:puesto_id>")
@role_required("admin")
def desactivar(puesto_id):
    set_activo(puesto_id, 0)
    log_audit(session, "deactivate", "puestos", puesto_id)
    return redirect(url_for("puestos.listado"))
