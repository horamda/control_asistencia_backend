from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from utils.forms import parse_float as _parse_float, parse_int as _parse_int
from repositories.sucursal_repository import (
    get_all,
    get_by_id,
    create,
    update,
    set_activa
)
from repositories.empresa_repository import get_all as get_empresas
from utils.audit import log_audit

sucursales_bp = Blueprint("sucursales", __name__, url_prefix="/sucursales")



def _extract_form_data(form):
    return {
        "empresa_id": _parse_int(form.get("empresa_id")),
        "nombre": (form.get("nombre") or "").strip(),
        "direccion": (form.get("direccion") or "").strip(),
        "latitud": _parse_float(form.get("latitud")),
        "longitud": _parse_float(form.get("longitud")),
        "radio_permitido_m": _parse_int(form.get("radio_permitido_m")),
        "activa": form.get("activa") == "1"
    }


def _validate_form(form):
    errors = []
    if not (form.get("empresa_id") or "").strip():
        errors.append("Empresa es requerida.")
    if not (form.get("nombre") or "").strip():
        errors.append("Nombre es requerido.")

    for field, label in [
        ("empresa_id", "Empresa"),
        ("radio_permitido_m", "Radio permitido")
    ]:
        value = (form.get(field) or "").strip()
        if value and not value.isdigit():
            errors.append(f"{label} debe ser numérico.")

    for field, label in [
        ("latitud", "Latitud"),
        ("longitud", "Longitud")
    ]:
        value = (form.get(field) or "").strip()
        if value:
            try:
                float(value)
            except ValueError:
                errors.append(f"{label} debe ser numérico.")

    return errors


@sucursales_bp.route("/")
@role_required("admin")
def listado():
    sucursales = get_all(include_inactive=True)
    return render_template("sucursales/listado.html", sucursales=sucursales)


@sucursales_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empresas = get_empresas()
    if request.method == "POST":
        errors = _validate_form(request.form)
        data = _extract_form_data(request.form)
        if errors:
            return render_template(
                "sucursales/form.html",
                mode="new",
                data=data,
                errors=errors,
                empresas=empresas
            )

        suc_id = create(data)
        log_audit(session, "create", "sucursales", suc_id)
        return redirect(url_for("sucursales.listado"))

    return render_template(
        "sucursales/form.html",
        mode="new",
        data={},
        empresas=empresas
    )


@sucursales_bp.route("/editar/<int:sucursal_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(sucursal_id):
    suc = get_by_id(sucursal_id)
    if not suc:
        abort(404)

    empresas = get_empresas(include_inactive=True)

    if request.method == "POST":
        errors = _validate_form(request.form)
        data = _extract_form_data(request.form)
        if errors:
            merged = dict(suc)
            merged.update(data)
            return render_template(
                "sucursales/form.html",
                mode="edit",
                data=merged,
                errors=errors,
                empresas=empresas
            )

        update(sucursal_id, data)
        log_audit(session, "update", "sucursales", sucursal_id)
        return redirect(url_for("sucursales.listado"))

    return render_template(
        "sucursales/form.html",
        mode="edit",
        data=suc,
        empresas=empresas
    )


@sucursales_bp.route("/activar/<int:sucursal_id>")
@role_required("admin")
def activar(sucursal_id):
    set_activa(sucursal_id, 1)
    log_audit(session, "activate", "sucursales", sucursal_id)
    return redirect(url_for("sucursales.listado"))


@sucursales_bp.route("/desactivar/<int:sucursal_id>")
@role_required("admin")
def desactivar(sucursal_id):
    set_activa(sucursal_id, 0)
    log_audit(session, "deactivate", "sucursales", sucursal_id)
    return redirect(url_for("sucursales.listado"))
