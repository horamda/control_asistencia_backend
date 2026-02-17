from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.franco_repository import get_all, get_by_id, create, update, delete
from repositories.empleado_repository import get_all as get_empleados
from utils.audit import log_audit

francos_bp = Blueprint("francos", __name__, url_prefix="/francos")


def _extract(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "fecha": (form.get("fecha") or "").strip(),
        "motivo": (form.get("motivo") or "").strip()
    }


def _validate(form):
    errors = []
    if not (form.get("empleado_id") or "").isdigit():
        errors.append("Empleado es requerido.")
    if not (form.get("fecha") or "").strip():
        errors.append("Fecha es requerida.")
    return errors


@francos_bp.route("/")
@role_required("admin")
def listado():
    francos = get_all()
    return render_template("francos/listado.html", francos=francos)


@francos_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        if errors:
            return render_template("francos/form.html", mode="new", data=data, errors=errors, empleados=empleados)
        franco_id = create(data)
        log_audit(session, "create", "francos", franco_id)
        return redirect(url_for("francos.listado"))

    return render_template("francos/form.html", mode="new", data={}, empleados=empleados)


@francos_bp.route("/editar/<int:franco_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(franco_id):
    franco = get_by_id(franco_id)
    if not franco:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        if errors:
            merged = dict(franco)
            merged.update(data)
            return render_template("francos/form.html", mode="edit", data=merged, errors=errors, empleados=empleados)
        update(franco_id, data)
        log_audit(session, "update", "francos", franco_id)
        return redirect(url_for("francos.listado"))

    return render_template("francos/form.html", mode="edit", data=franco, empleados=empleados)


@francos_bp.route("/eliminar/<int:franco_id>", methods=["POST"])
@role_required("admin")
def eliminar(franco_id):
    delete(franco_id)
    log_audit(session, "delete", "francos", franco_id)
    return redirect(url_for("francos.listado"))
