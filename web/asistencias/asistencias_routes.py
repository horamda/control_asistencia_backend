import datetime

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from repositories.asistencia_repository import create, delete, get_by_id, get_page, update
from repositories.empleado_repository import get_all as get_empleados
from utils.asistencia import generar_ausentes, get_horario_esperado, validar_asistencia
from utils.audit import log_audit
from web.auth.decorators import role_required

asistencias_bp = Blueprint("asistencias", __name__, url_prefix="/asistencias")


def _parse_float(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _extract_form_data(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "fecha": (form.get("fecha") or "").strip(),
        "hora_entrada": (form.get("hora_entrada") or "").strip(),
        "hora_salida": (form.get("hora_salida") or "").strip(),
        "lat_entrada": _parse_float(form.get("lat_entrada")),
        "lon_entrada": _parse_float(form.get("lon_entrada")),
        "lat_salida": _parse_float(form.get("lat_salida")),
        "lon_salida": _parse_float(form.get("lon_salida")),
        "foto_entrada": (form.get("foto_entrada") or "").strip(),
        "foto_salida": (form.get("foto_salida") or "").strip(),
        "metodo_entrada": (form.get("metodo_entrada") or "").strip(),
        "metodo_salida": (form.get("metodo_salida") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip(),
    }


def _validate(form):
    errors = []
    if not (form.get("empleado_id") or "").isdigit():
        errors.append("Empleado es requerido.")
    if not (form.get("fecha") or "").strip():
        errors.append("Fecha es requerida.")

    for field, label, min_v, max_v in [
        ("lat_entrada", "Lat entrada", -90, 90),
        ("lat_salida", "Lat salida", -90, 90),
        ("lon_entrada", "Lon entrada", -180, 180),
        ("lon_salida", "Lon salida", -180, 180),
    ]:
        value = (form.get(field) or "").strip()
        if value:
            try:
                v = float(value)
            except ValueError:
                errors.append(f"{label} invalida.")
                continue
            if v < min_v or v > max_v:
                errors.append(f"{label} fuera de rango.")

    for field, label in [
        ("metodo_entrada", "Metodo entrada"),
        ("metodo_salida", "Metodo salida"),
    ]:
        value = (form.get(field) or "").strip()
        if value and value not in {"qr", "manual", "facial"}:
            errors.append(f"{label} invalido.")

    empleado_id = int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None
    fecha = (form.get("fecha") or "").strip()
    hora_entrada = (form.get("hora_entrada") or "").strip()
    hora_salida = (form.get("hora_salida") or "").strip()
    extra_errors, _ = validar_asistencia(empleado_id, fecha, hora_entrada, hora_salida)
    errors.extend(extra_errors)
    return errors


@asistencias_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    search = request.args.get("q")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    asistencias, total = get_page(page, per_page, empleado_id, fecha_desde, fecha_hasta, search)
    empleados = get_empleados(include_inactive=True)
    return render_template(
        "asistencias/listado.html",
        asistencias=asistencias,
        empleados=empleados,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        q=search,
        page=page,
        per_page=per_page,
        total=total,
        today=datetime.date.today().isoformat(),
    )


@asistencias_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract_form_data(request.form)
        if errors:
            return render_template("asistencias/form.html", mode="new", data=data, errors=errors, empleados=empleados)

        _, estado_calc = validar_asistencia(
            data.get("empleado_id"),
            data.get("fecha"),
            data.get("hora_entrada"),
            data.get("hora_salida"),
        )
        data["estado"] = estado_calc or ("ausente" if not data.get("hora_entrada") and not data.get("hora_salida") else "ok")

        asistencia_id = create(data)
        log_audit(session, "create", "asistencias", asistencia_id)
        return redirect(url_for("asistencias.listado"))

    return render_template("asistencias/form.html", mode="new", data={}, empleados=empleados)


@asistencias_bp.route("/generar-ausentes", methods=["POST"])
@role_required("admin")
def generar_ausentes_post():
    fecha = (request.form.get("fecha") or "").strip()
    if not fecha:
        return redirect(url_for("asistencias.listado"))
    generar_ausentes(fecha)
    return redirect(url_for("asistencias.listado", fecha_desde=fecha, fecha_hasta=fecha))


@asistencias_bp.route("/editar/<int:asistencia_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(asistencia_id):
    asistencia = get_by_id(asistencia_id)
    if not asistencia:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract_form_data(request.form)
        if errors:
            merged = dict(asistencia)
            merged.update(data)
            return render_template("asistencias/form.html", mode="edit", data=merged, errors=errors, empleados=empleados)

        _, estado_calc = validar_asistencia(
            data.get("empleado_id"),
            data.get("fecha"),
            data.get("hora_entrada"),
            data.get("hora_salida"),
        )
        data["estado"] = estado_calc or ("ausente" if not data.get("hora_entrada") and not data.get("hora_salida") else "ok")

        update(asistencia_id, data)
        log_audit(session, "update", "asistencias", asistencia_id)
        return redirect(url_for("asistencias.listado"))

    return render_template("asistencias/form.html", mode="edit", data=asistencia, empleados=empleados)


@asistencias_bp.route("/eliminar/<int:asistencia_id>", methods=["POST"])
@role_required("admin")
def eliminar(asistencia_id):
    delete(asistencia_id)
    log_audit(session, "delete", "asistencias", asistencia_id)
    return redirect(url_for("asistencias.listado"))


@asistencias_bp.route("/horario-esperado")
@role_required("admin")
def horario_esperado():
    empleado_id = request.args.get("empleado_id", type=int)
    fecha = (request.args.get("fecha") or "").strip()
    if not empleado_id or not fecha:
        return jsonify({"error": "empleado_id y fecha son requeridos"}), 400
    try:
        data = get_horario_esperado(empleado_id, fecha)
    except ValueError:
        return jsonify({"error": "fecha invalida"}), 400
    if not data:
        return jsonify({"error": "sin horario esperado"}), 404
    return jsonify(data)
