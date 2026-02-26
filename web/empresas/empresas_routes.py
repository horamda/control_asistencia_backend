from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.empresa_repository import (
    get_all,
    get_by_id,
    create,
    update,
    set_activa
)
from utils.audit import log_audit

empresas_bp = Blueprint("empresas", __name__, url_prefix="/empresas")


def _extract_form_data(form):
    return {
        "razon_social": (form.get("razon_social") or "").strip(),
        "nombre_fantasia": (form.get("nombre_fantasia") or "").strip(),
        "cuit": (form.get("cuit") or "").strip(),
        "logo": (form.get("logo") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "telefono": (form.get("telefono") or "").strip(),
        "direccion": (form.get("direccion") or "").strip(),
        "activa": form.get("activa") == "1"
    }


def _validate_form(form):
    errors = []
    if not (form.get("razon_social") or "").strip():
        errors.append("Razon social es requerida.")
    if not (form.get("cuit") or "").strip():
        errors.append("CUIT es requerido.")

    email = (form.get("email") or "").strip()
    if email and "@" not in email:
        errors.append("Email invalido.")

    return errors


@empresas_bp.route("/")
@role_required("admin")
def listado():
    empresas = get_all(include_inactive=True)
    return render_template("empresas/listado.html", empresas=empresas)


@empresas_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    if request.method == "POST":
        errors = _validate_form(request.form)
        data = _extract_form_data(request.form)
        if errors:
            return render_template("empresas/form.html", mode="new", data=data, errors=errors)

        emp_id = create(data)
        log_audit(session, "create", "empresas", emp_id)
        return redirect(url_for("empresas.listado"))

    return render_template("empresas/form.html", mode="new", data={})


@empresas_bp.route("/editar/<int:empresa_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(empresa_id):
    emp = get_by_id(empresa_id)
    if not emp:
        abort(404)

    if request.method == "POST":
        errors = _validate_form(request.form)
        data = _extract_form_data(request.form)
        if errors:
            merged = dict(emp)
            merged.update(data)
            return render_template("empresas/form.html", mode="edit", data=merged, errors=errors)

        update(empresa_id, data)
        log_audit(session, "update", "empresas", empresa_id)
        return redirect(url_for("empresas.listado"))

    return render_template("empresas/form.html", mode="edit", data=emp)


@empresas_bp.route("/activar/<int:empresa_id>")
@role_required("admin")
def activar(empresa_id):
    set_activa(empresa_id, 1)
    log_audit(session, "activate", "empresas", empresa_id)
    return redirect(url_for("empresas.listado"))


@empresas_bp.route("/desactivar/<int:empresa_id>")
@role_required("admin")
def desactivar(empresa_id):
    set_activa(empresa_id, 0)
    log_audit(session, "deactivate", "empresas", empresa_id)
    return redirect(url_for("empresas.listado"))
