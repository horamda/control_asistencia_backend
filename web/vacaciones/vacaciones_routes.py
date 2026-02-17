from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.vacacion_repository import get_all, get_by_id, create, update, delete
from repositories.empleado_repository import get_all as get_empleados
from utils.audit import log_audit

vacaciones_bp = Blueprint("vacaciones", __name__, url_prefix="/vacaciones")


def _extract(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "fecha_desde": (form.get("fecha_desde") or "").strip(),
        "fecha_hasta": (form.get("fecha_hasta") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip()
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
@role_required("admin")
def listado():
    vacaciones = get_all()
    return render_template("vacaciones/listado.html", vacaciones=vacaciones)


@vacaciones_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
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
@role_required("admin")
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
@role_required("admin")
def eliminar(vacacion_id):
    delete(vacacion_id)
    log_audit(session, "delete", "vacaciones", vacacion_id)
    return redirect(url_for("vacaciones.listado"))
