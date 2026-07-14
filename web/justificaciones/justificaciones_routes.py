from datetime import date

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for

from repositories.asistencia_repository import get_all as get_asistencias
from repositories.empleado_repository import get_all as get_empleados
from repositories.justificacion_repository import delete, get_by_id, get_page
from services.justificacion_attachment_service import (
    delete_justificacion_adjunto,
    delete_justificacion_resources,
    list_justificacion_adjuntos,
    save_justificacion_adjuntos,
    sync_justificacion_event,
)
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
ESTADOS_VALIDOS = {"pendiente", "aprobada", "rechazada"}


def _extract_form_data(form) -> dict:
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "asistencia_id": int(form.get("asistencia_id")) if (form.get("asistencia_id") or "").isdigit() else None,
        "asistencia_id_present": "asistencia_id" in form,
        "fecha": (form.get("fecha") or "").strip() or None,
        "fecha_desde": (form.get("fecha_desde") or "").strip() or None,
        "fecha_hasta": (form.get("fecha_hasta") or "").strip() or None,
        "motivo": (form.get("motivo") or "").strip(),
        "archivo": (form.get("archivo") or "").strip(),
        "estado": (form.get("estado") or "").strip() or None,
    }


def _extract_adjuntos_from_request():
    adjuntos = request.files.getlist("adjuntos")
    if not adjuntos:
        adjuntos = request.files.getlist("adjuntos[]")
    if not adjuntos:
        archivo_unico = request.files.get("archivo_file")
        if not archivo_unico:
            archivo_unico = request.files.get("archivo")
        if archivo_unico and str(archivo_unico.filename or "").strip():
            adjuntos = [archivo_unico]
    return adjuntos


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
    estado = (request.args.get("estado") or "").strip().lower() or None
    if estado and estado not in ESTADOS_VALIDOS:
        estado = None
    justificaciones, total = get_page(page, per_page, empleado_id, fecha_desde, fecha_hasta, search, estado)
    adjuntos_por_justificacion = {
        int(justificacion["id"]): list_justificacion_adjuntos(int(justificacion["id"]))
        for justificacion in justificaciones
        if justificacion.get("adjuntos_count")
    }
    empleados = get_empleados(include_inactive=True)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None
    return render_template(
        "justificaciones/listado.html",
        justificaciones=justificaciones,
        adjuntos_por_justificacion=adjuntos_por_justificacion,
        empleados=empleados,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=estado,
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
    today = date.today().isoformat()
    if request.method == "POST":
        data = _extract_form_data(request.form)
        if not data["asistencia_id_present"]:
            data["asistencia_id"] = None
        data["estado"] = "pendiente"
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
                today=today,
            )
        try:
            sync_justificacion_event(int(just_id), actor_id=session.get("user_id"))
            adjuntos = _extract_adjuntos_from_request()
            if adjuntos:
                save_justificacion_adjuntos(int(just_id), adjuntos, actor_id=session.get("user_id"))
        except Exception as exc:
            try:
                delete_justificacion_resources(int(just_id), actor_id=session.get("user_id"))
                delete(just_id)
            except Exception:
                current_app.logger.exception("web_justificaciones_create_rollback_error")
            return render_template(
                "justificaciones/form.html",
                mode="new",
                data=data,
                errors=[str(exc)],
                empleados=empleados,
                asistencias=asistencias,
                today=today,
            )
        log_audit(session, "create", "justificaciones", just_id)
        return redirect(url_for("justificaciones.listado", msg="Justificacion creada."))

    return render_template(
        "justificaciones/form.html",
        mode="new",
        data={},
        empleados=empleados,
        asistencias=asistencias,
        today=today,
    )


@justificaciones_bp.post("/<int:justificacion_id>/adjuntos/<int:adjunto_id>/eliminar")
@role_required("admin", "rrhh", "supervisor")
def eliminar_adjunto(justificacion_id: int, adjunto_id: int):
    try:
        delete_justificacion_adjunto(
            justificacion_id,
            adjunto_id,
            actor_id=session.get("user_id"),
        )
    except ValueError as exc:
        return redirect(url_for("justificaciones.editar", justificacion_id=justificacion_id, error=str(exc)))
    log_audit(session, "delete_attachment", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.editar", justificacion_id=justificacion_id, msg="Adjunto eliminado."))


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
    adjuntos_existentes = list_justificacion_adjuntos(justificacion_id)
    today = date.today().isoformat()
    if request.method == "POST":
        data = _extract_form_data(request.form)
        # Preserve current estado — estado only changes via dedicated endpoints
        data["estado"] = justificacion.get("estado") or "pendiente"
        if not data["asistencia_id_present"]:
            data["asistencia_id"] = justificacion.get("asistencia_id")
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
                adjuntos=adjuntos_existentes,
                today=today,
            )
        try:
            sync_justificacion_event(int(justificacion_id), actor_id=session.get("user_id"))
            adjuntos = _extract_adjuntos_from_request()
            if adjuntos:
                save_justificacion_adjuntos(int(justificacion_id), adjuntos, actor_id=session.get("user_id"))
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
                adjuntos=adjuntos_existentes,
                today=today,
            )
        log_audit(session, "update", "justificaciones", justificacion_id)
        return redirect(url_for("justificaciones.listado", msg="Justificacion actualizada."))

    return render_template(
        "justificaciones/form.html",
        mode="edit",
        data=justificacion,
        errors=[request.args.get("error")] if request.args.get("error") else None,
        empleados=empleados,
        asistencias=asistencias,
        adjuntos=adjuntos_existentes,
        today=today,
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
    try:
        delete_justificacion_resources(int(justificacion_id), actor_id=session.get("user_id"))
        delete(justificacion_id)
    except Exception:
        current_app.logger.exception(
            "web_justificaciones_delete_error",
            extra={"extra": {"justificacion_id": justificacion_id}},
        )
        return redirect(
            url_for(
                "justificaciones.listado",
                error="No se pudo eliminar la justificacion.",
            )
        )
    log_audit(session, "delete", "justificaciones", justificacion_id)
    return redirect(url_for("justificaciones.listado", msg="Justificacion eliminada."))
