from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.localidad_repository import get_all, get_by_codigo, create, update, delete
from utils.audit import log_audit

localidades_bp = Blueprint("localidades", __name__, url_prefix="/localidades")


def _extract(form):
    return {
        "codigo_postal": (form.get("codigo_postal") or "").strip(),
        "localidad": (form.get("localidad") or "").strip(),
        "provincia": (form.get("provincia") or "").strip(),
        "pais": (form.get("pais") or "").strip()
    }


def _validate(form, is_new: bool):
    errors = []
    if is_new and not (form.get("codigo_postal") or "").strip():
        errors.append("Código postal es requerido.")
    if not (form.get("localidad") or "").strip():
        errors.append("Localidad es requerida.")
    if not (form.get("provincia") or "").strip():
        errors.append("Provincia es requerida.")
    if not (form.get("pais") or "").strip():
        errors.append("País es requerido.")
    return errors


@localidades_bp.route("/")
@role_required("admin")
def listado():
    localidades = get_all()
    return render_template("localidades/listado.html", localidades=localidades)


@localidades_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    if request.method == "POST":
        errors = _validate(request.form, is_new=True)
        data = _extract(request.form)
        if errors:
            return render_template("localidades/form.html", mode="new", data=data, errors=errors)
        create(data)
        log_audit(session, "create", "localidades", None)
        return redirect(url_for("localidades.listado"))

    return render_template("localidades/form.html", mode="new", data={})


@localidades_bp.route("/editar/<codigo_postal>", methods=["GET", "POST"])
@role_required("admin")
def editar(codigo_postal):
    loc = get_by_codigo(codigo_postal)
    if not loc:
        abort(404)

    if request.method == "POST":
        errors = _validate(request.form, is_new=False)
        data = _extract(request.form)
        if errors:
            merged = dict(loc)
            merged.update(data)
            return render_template("localidades/form.html", mode="edit", data=merged, errors=errors)
        update(codigo_postal, data)
        log_audit(session, "update", "localidades", None)
        return redirect(url_for("localidades.listado"))

    return render_template("localidades/form.html", mode="edit", data=loc)


@localidades_bp.route("/eliminar/<codigo_postal>", methods=["POST"])
@role_required("admin")
def eliminar(codigo_postal):
    delete(codigo_postal)
    log_audit(session, "delete", "localidades", None)
    return redirect(url_for("localidades.listado"))
