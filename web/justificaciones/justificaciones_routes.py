from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.justificacion_repository import get_page, get_by_id, create, update, delete
from repositories.empleado_repository import get_all as get_empleados
from repositories.asistencia_repository import get_all as get_asistencias
from utils.audit import log_audit

justificaciones_bp = Blueprint("justificaciones", __name__, url_prefix="/justificaciones")


def _extract_form_data(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if form.get("empleado_id") and form.get("empleado_id").isdigit() else None,
        "asistencia_id": int(form.get("asistencia_id")) if form.get("asistencia_id") and form.get("asistencia_id").isdigit() else None,
        "motivo": (form.get("motivo") or "").strip(),
        "archivo": (form.get("archivo") or "").strip(),
        "estado": (form.get("estado") or "").strip()
    }


def _validate(form):
    errors = []
    if not (form.get("empleado_id") or "").isdigit():
        errors.append("Empleado es requerido.")
    if not (form.get("motivo") or "").strip():
        errors.append("Motivo es requerido.")
    estado = (form.get("estado") or "").strip()
    if estado and estado not in {"pendiente", "aprobada", "rechazada"}:
        errors.append("Estado inválido.")
    return errors


@justificaciones_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    search = request.args.get("q")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    justificaciones, total = get_page(page, per_page, empleado_id, fecha_desde, fecha_hasta, search)
    empleados = get_empleados(include_inactive=True)
    return render_template(
        "justificaciones/listado.html",
        justificaciones=justificaciones,
        empleados=empleados,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@justificaciones_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    asistencias = get_asistencias()
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract_form_data(request.form)
        if errors:
            return render_template(
                "justificaciones/form.html",
                mode="new",
                data=data,
                errors=errors,
                empleados=empleados,
                asistencias=asistencias
            )
        just_id = create(data)
        log_audit(session, "create", "justificaciones", just_id)
        return redirect(url_for("justificaciones.listado"))

    return render_template(
        "justificaciones/form.html",
        mode="new",
        data={},
        empleados=empleados,
        asistencias=asistencias
    )


@justificaciones_bp.route("/editar/<int:justificacion_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(justificacion_id):
    justificacion = get_by_id(justificacion_id)
    if not justificacion:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    asistencias = get_asistencias()
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract_form_data(request.form)
        if errors:
            merged = dict(justificacion)
            merged.update(data)
            return render_template(
                "justificaciones/form.html",
                mode="edit",
                data=merged,
                errors=errors,
                empleados=empleados,
                asistencias=asistencias
            )
        update(justificacion_id, data)
        log_audit(session, "update", "justificaciones", justificacion_id)
        return redirect(url_for("justificaciones.listado"))

    return render_template(
        "justificaciones/form.html",
        mode="edit",
        data=justificacion,
        empleados=empleados,
        asistencias=asistencias
    )


@justificaciones_bp.route("/eliminar/<int:justificacion_id>", methods=["POST"])
@role_required("admin")
def eliminar(justificacion_id):
    delete(justificacion_id)
    log_audit(session, "delete", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.listado"))
