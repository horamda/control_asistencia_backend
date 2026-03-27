from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from repositories.asistencia_repository import get_all as get_asistencias
from repositories.empleado_repository import get_all as get_empleados
from repositories.justificacion_repository import delete, get_by_id, get_page
from services.justificacion_service import (
    aprobar_justificacion,
    create_justificacion,
    rechazar_justificacion,
    revertir_justificacion,
    update_justificacion,
)
from utils.audit import log_audit
from web.auth.decorators import role_required

justificaciones_bp = Blueprint("justificaciones", __name__, url_prefix="/justificaciones")


def _extract_form_data(form) -> dict:
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "asistencia_id": int(form.get("asistencia_id")) if (form.get("asistencia_id") or "").isdigit() else None,
        "motivo": (form.get("motivo") or "").strip(),
        "archivo": (form.get("archivo") or "").strip(),
        "estado": (form.get("estado") or "").strip() or None,
    }


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------

@justificaciones_bp.route("/")
@role_required("admin", "rrhh", "supervisor")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    search = request.args.get("q")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    justificaciones, total = get_page(page, per_page, empleado_id, fecha_desde, fecha_hasta, search)
    empleados = get_empleados(include_inactive=True)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
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
        total=total,
        error=error,
        msg=msg,
    )


# ---------------------------------------------------------------------------
# Crear
# ---------------------------------------------------------------------------

@justificaciones_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh", "supervisor")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    asistencias = get_asistencias()
    if request.method == "POST":
        data = _extract_form_data(request.form)
        try:
            just_id = create_justificacion(data)
        except ValueError as exc:
            return render_template(
                "justificaciones/form.html",
                mode="new",
                data=data,
                errors=[str(exc)],
                empleados=empleados,
                asistencias=asistencias,
            )
        log_audit(session, "create", "justificaciones", just_id)
        return redirect(url_for("justificaciones.listado", msg="Justificacion creada."))

    return render_template(
        "justificaciones/form.html",
        mode="new",
        data={},
        empleados=empleados,
        asistencias=asistencias,
    )


# ---------------------------------------------------------------------------
# Editar (motivo + archivo — NO estado; usar aprobar/rechazar/revertir)
# ---------------------------------------------------------------------------

@justificaciones_bp.route("/editar/<int:justificacion_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh", "supervisor")
def editar(justificacion_id):
    justificacion = get_by_id(justificacion_id)
    if not justificacion:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    asistencias = get_asistencias()
    if request.method == "POST":
        data = _extract_form_data(request.form)
        # Preserve current estado — estado only changes via dedicated endpoints
        data["estado"] = justificacion.get("estado") or "pendiente"
        try:
            update_justificacion(justificacion_id, data)
        except ValueError as exc:
            merged = dict(justificacion)
            merged.update(data)
            return render_template(
                "justificaciones/form.html",
                mode="edit",
                data=merged,
                errors=[str(exc)],
                empleados=empleados,
                asistencias=asistencias,
            )
        log_audit(session, "update", "justificaciones", justificacion_id)
        return redirect(url_for("justificaciones.listado", msg="Justificacion actualizada."))

    return render_template(
        "justificaciones/form.html",
        mode="edit",
        data=justificacion,
        empleados=empleados,
        asistencias=asistencias,
    )


# ---------------------------------------------------------------------------
# Acciones de estado
# ---------------------------------------------------------------------------

@justificaciones_bp.route("/aprobar/<int:justificacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def aprobar(justificacion_id):
    try:
        aprobar_justificacion(justificacion_id)
    except ValueError as exc:
        return redirect(url_for("justificaciones.listado", error=str(exc)))
    log_audit(session, "aprobar", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.listado", msg="Justificacion aprobada."))


@justificaciones_bp.route("/rechazar/<int:justificacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def rechazar(justificacion_id):
    try:
        rechazar_justificacion(justificacion_id)
    except ValueError as exc:
        return redirect(url_for("justificaciones.listado", error=str(exc)))
    log_audit(session, "rechazar", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.listado", msg="Justificacion rechazada."))


@justificaciones_bp.route("/revertir/<int:justificacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def revertir(justificacion_id):
    try:
        revertir_justificacion(justificacion_id)
    except ValueError as exc:
        return redirect(url_for("justificaciones.listado", error=str(exc)))
    log_audit(session, "revertir", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.listado", msg="Justificacion revertida a pendiente."))


# ---------------------------------------------------------------------------
# Eliminar
# ---------------------------------------------------------------------------

@justificaciones_bp.route("/eliminar/<int:justificacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar(justificacion_id):
    delete(justificacion_id)
    log_audit(session, "delete", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.listado", msg="Justificacion eliminada."))
