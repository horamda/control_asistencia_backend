import datetime

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from repositories.empleado_horario_repository import (
    create_asignacion,
    delete_asignacion,
    get_actual_by_empleado,
    get_asignacion_by_id,
    get_historial,
    update_asignacion,
)
from repositories.empleado_repository import get_all, get_by_id
from repositories.horario_repository import get_all as get_horarios
from repositories.horario_repository import get_by_id as get_horario_by_id
from utils.audit import log_audit
from web.auth.decorators import role_required

empleado_horarios_bp = Blueprint("empleado_horarios", __name__, url_prefix="/empleado-horarios")


def _validate_fields(horario_id_raw: str, fecha_desde: str, fecha_hasta: str | None):
    errors = []
    horario_id = None
    if not horario_id_raw or not horario_id_raw.isdigit():
        errors.append("Horario es requerido.")
    else:
        horario_id = int(horario_id_raw)

    if not fecha_desde:
        errors.append("Fecha desde es requerida.")
    else:
        try:
            datetime.date.fromisoformat(fecha_desde)
        except ValueError:
            errors.append("Fecha desde invalida.")

    if fecha_hasta:
        try:
            datetime.date.fromisoformat(fecha_hasta)
        except ValueError:
            errors.append("Fecha hasta invalida.")

    if fecha_desde and fecha_hasta:
        try:
            if datetime.date.fromisoformat(fecha_desde) > datetime.date.fromisoformat(fecha_hasta):
                errors.append("Fecha desde no puede ser mayor que fecha hasta.")
        except ValueError:
            pass
    return errors, horario_id


def _empresa_filter(horarios, empresa_id):
    return [h for h in horarios if h.get("empresa_id") == empresa_id]


def _render_form(empleado, horarios, actual, historial, data, errors=None, mode="new", asignacion=None):
    return render_template(
        "empleado_horarios/form.html",
        empleado=empleado,
        horarios=horarios,
        actual=actual,
        historial=historial,
        data=data,
        errors=errors or [],
        mode=mode,
        asignacion=asignacion,
    )


@empleado_horarios_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    empleados = get_all(include_inactive=True)
    return render_template("empleado_horarios/listado.html", empleados=empleados)


@empleado_horarios_bp.route("/<int:empleado_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def asignar(empleado_id):
    empleado = get_by_id(empleado_id)
    if not empleado:
        abort(404)

    horarios = _empresa_filter(get_horarios(include_inactive=True), empleado.get("empresa_id"))
    actual = get_actual_by_empleado(empleado_id)
    historial = get_historial(empleado_id)

    if request.method == "POST":
        horario_id_raw = (request.form.get("horario_id") or "").strip()
        fecha_desde = (request.form.get("fecha_desde") or "").strip()
        fecha_hasta = (request.form.get("fecha_hasta") or "").strip() or None
        errors, horario_id = _validate_fields(horario_id_raw, fecha_desde, fecha_hasta)

        horario = get_horario_by_id(horario_id) if horario_id else None
        if horario and horario.get("empresa_id") != empleado.get("empresa_id"):
            errors.append("El horario debe pertenecer a la misma empresa del empleado.")
        if not horario:
            errors.append("Horario invalido.")

        if errors:
            return _render_form(
                empleado,
                horarios,
                actual,
                historial,
                {"horario_id": horario_id, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta or ""},
                errors=errors,
            )

        try:
            asignacion_id = create_asignacion(
                empleado_id,
                horario_id,
                fecha_desde,
                fecha_hasta,
                empleado.get("empresa_id"),
            )
        except ValueError as exc:
            return _render_form(
                empleado,
                horarios,
                actual,
                historial,
                {"horario_id": horario_id, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta or ""},
                errors=[str(exc)],
            )

        log_audit(session, "assign", "empleado_horarios", asignacion_id)
        return redirect(url_for("empleado_horarios.asignar", empleado_id=empleado_id))

    return _render_form(empleado, horarios, actual, historial, {}, mode="new")


@empleado_horarios_bp.route("/<int:empleado_id>/editar/<int:asignacion_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(empleado_id, asignacion_id):
    empleado = get_by_id(empleado_id)
    if not empleado:
        abort(404)

    asignacion = get_asignacion_by_id(asignacion_id)
    if not asignacion or asignacion.get("empleado_id") != empleado_id:
        abort(404)

    horarios = _empresa_filter(get_horarios(include_inactive=True), empleado.get("empresa_id"))
    actual = get_actual_by_empleado(empleado_id)
    historial = get_historial(empleado_id)

    if request.method == "POST":
        horario_id_raw = (request.form.get("horario_id") or "").strip()
        fecha_desde = (request.form.get("fecha_desde") or "").strip()
        fecha_hasta = (request.form.get("fecha_hasta") or "").strip() or None
        errors, horario_id = _validate_fields(horario_id_raw, fecha_desde, fecha_hasta)

        horario = get_horario_by_id(horario_id) if horario_id else None
        if horario and horario.get("empresa_id") != empleado.get("empresa_id"):
            errors.append("El horario debe pertenecer a la misma empresa del empleado.")
        if not horario:
            errors.append("Horario invalido.")

        if errors:
            return _render_form(
                empleado,
                horarios,
                actual,
                historial,
                {"horario_id": horario_id, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta or ""},
                errors=errors,
                mode="edit",
                asignacion=asignacion,
            )

        try:
            update_asignacion(
                asignacion_id,
                empleado_id,
                horario_id,
                fecha_desde,
                fecha_hasta,
                empleado.get("empresa_id"),
            )
        except ValueError as exc:
            return _render_form(
                empleado,
                horarios,
                actual,
                historial,
                {"horario_id": horario_id, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta or ""},
                errors=[str(exc)],
                mode="edit",
                asignacion=asignacion,
            )

        log_audit(session, "update", "empleado_horarios", asignacion_id)
        return redirect(url_for("empleado_horarios.asignar", empleado_id=empleado_id))

    data = {
        "horario_id": asignacion.get("horario_id"),
        "fecha_desde": str(asignacion.get("fecha_desde") or ""),
        "fecha_hasta": str(asignacion.get("fecha_hasta") or ""),
    }
    return _render_form(empleado, horarios, actual, historial, data, mode="edit", asignacion=asignacion)


@empleado_horarios_bp.route("/<int:empleado_id>/eliminar/<int:asignacion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar(empleado_id, asignacion_id):
    empleado = get_by_id(empleado_id)
    if not empleado:
        abort(404)
    if not delete_asignacion(asignacion_id, empleado_id):
        abort(404)
    log_audit(session, "delete", "empleado_horarios", asignacion_id)
    return redirect(url_for("empleado_horarios.asignar", empleado_id=empleado_id))


@empleado_horarios_bp.route("/api/<int:empleado_id>", methods=["GET"])
@role_required("admin", "rrhh")
def api_historial(empleado_id):
    empleado = get_by_id(empleado_id)
    if not empleado:
        return jsonify({"error": "Empleado no encontrado"}), 404
    return jsonify(
        {
            "empleado": {
                "id": empleado["id"],
                "empresa_id": empleado.get("empresa_id"),
                "nombre": empleado.get("nombre"),
                "apellido": empleado.get("apellido"),
            },
            "actual": get_actual_by_empleado(empleado_id),
            "historial": get_historial(empleado_id),
        }
    )


@empleado_horarios_bp.route("/api", methods=["POST"])
@role_required("admin", "rrhh")
def api_asignar():
    payload = request.get_json(silent=True) or {}
    try:
        empleado_id = int(payload.get("empleado_id"))
        horario_id = int(payload.get("horario_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "empleado_id y horario_id deben ser numericos"}), 400

    fecha_desde = str(payload.get("fecha_desde") or "").strip()
    fecha_hasta = str(payload.get("fecha_hasta") or "").strip() or None
    errors, _ = _validate_fields(str(horario_id), fecha_desde, fecha_hasta)
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    empleado = get_by_id(empleado_id)
    horario = get_horario_by_id(horario_id)
    if not empleado or not horario:
        return jsonify({"error": "Empleado u horario invalido"}), 400
    if empleado.get("empresa_id") != horario.get("empresa_id"):
        return jsonify({"error": "Empresa inconsistente entre empleado y horario"}), 400

    try:
        asignacion_id = create_asignacion(
            empleado_id,
            horario_id,
            fecha_desde,
            fecha_hasta,
            empleado.get("empresa_id"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    log_audit(session, "assign", "empleado_horarios", asignacion_id)
    return jsonify({"id": asignacion_id}), 201


@empleado_horarios_bp.route("/api/<int:asignacion_id>", methods=["PUT"])
@role_required("admin", "rrhh")
def api_editar(asignacion_id):
    payload = request.get_json(silent=True) or {}
    original = get_asignacion_by_id(asignacion_id)
    if not original:
        return jsonify({"error": "Asignacion no encontrada"}), 404

    try:
        horario_id = int(payload.get("horario_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "horario_id debe ser numerico"}), 400
    fecha_desde = str(payload.get("fecha_desde") or "").strip()
    fecha_hasta = str(payload.get("fecha_hasta") or "").strip() or None
    errors, _ = _validate_fields(str(horario_id), fecha_desde, fecha_hasta)
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    empleado = get_by_id(original["empleado_id"])
    horario = get_horario_by_id(horario_id)
    if not empleado or not horario:
        return jsonify({"error": "Empleado u horario invalido"}), 400
    if empleado.get("empresa_id") != horario.get("empresa_id"):
        return jsonify({"error": "Empresa inconsistente entre empleado y horario"}), 400

    try:
        update_asignacion(
            asignacion_id,
            original["empleado_id"],
            horario_id,
            fecha_desde,
            fecha_hasta,
            empleado.get("empresa_id"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    log_audit(session, "update", "empleado_horarios", asignacion_id)
    return jsonify({"ok": True})


@empleado_horarios_bp.route("/api/<int:asignacion_id>", methods=["DELETE"])
@role_required("admin", "rrhh")
def api_eliminar(asignacion_id):
    original = get_asignacion_by_id(asignacion_id)
    if not original:
        return jsonify({"error": "Asignacion no encontrada"}), 404
    if not delete_asignacion(asignacion_id, original["empleado_id"]):
        return jsonify({"error": "No se pudo eliminar"}), 400
    log_audit(session, "delete", "empleado_horarios", asignacion_id)
    return jsonify({"ok": True})

