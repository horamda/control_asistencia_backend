import datetime
import json

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from utils.forms import parse_int as _parse_int

from repositories.empleado_excepcion_repository import delete, get_all, get_by_id
from repositories.empleado_repository import get_all as get_empleados
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.excepcion_bloque_repository import get_by_excepcion
from services.excepcion_service import create_excepcion, update_excepcion
from utils.audit import log_audit
from web.auth.decorators import role_required

empleado_excepciones_bp = Blueprint("empleado_excepciones", __name__, url_prefix="/empleado-excepciones")

TIPOS = ["VACACIONES", "FRANCO", "FERIADO", "LICENCIA", "CAMBIO_HORARIO", "OTRO"]
TIPOS_ANULA = {"VACACIONES", "FRANCO", "FERIADO", "LICENCIA"}



def _parse_bloques_json(raw):
    raw = (raw or "").strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("Bloques JSON invalido.")
    blocks = []
    for i, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Bloque {i} invalido.")
        entrada = str(item.get("entrada") or "").strip()
        salida = str(item.get("salida") or "").strip()
        if not entrada or not salida:
            raise ValueError(f"Bloque {i}: entrada y salida son requeridas.")
        blocks.append({"entrada": entrada, "salida": salida})
    return blocks


def _extract(form):
    return {
        "empleado_id": _parse_int(form.get("empleado_id")),
        "fecha": (form.get("fecha") or "").strip(),
        "tipo": (form.get("tipo") or "").strip(),
        "descripcion": (form.get("descripcion") or "").strip(),
        "anula_horario": True if form.get("anula_horario") == "1" else False,
        "bloques_json": (form.get("bloques_json") or "").strip(),
    }


def _validate(form):
    errors = []
    empleado_id = (form.get("empleado_id") or "").strip()
    fecha = (form.get("fecha") or "").strip()
    tipo = (form.get("tipo") or "").strip()

    if not empleado_id or not empleado_id.isdigit():
        errors.append("Empleado es requerido.")
    if not fecha:
        errors.append("Fecha es requerida.")
    else:
        try:
            datetime.date.fromisoformat(fecha)
        except ValueError:
            errors.append("Fecha invalida.")
    if not tipo:
        errors.append("Tipo es requerido.")
    elif tipo not in TIPOS:
        errors.append("Tipo invalido.")
    return errors


def _serialize_excepcion_bloques(excepcion_id: int):
    rows = get_by_excepcion(excepcion_id)
    blocks = []
    for r in rows:
        entrada = r["hora_entrada"].strftime("%H:%M") if hasattr(r["hora_entrada"], "strftime") else str(r["hora_entrada"])[:5]
        salida = r["hora_salida"].strftime("%H:%M") if hasattr(r["hora_salida"], "strftime") else str(r["hora_salida"])[:5]
        blocks.append({"entrada": entrada, "salida": salida})
    return json.dumps(blocks, ensure_ascii=False)


@empleado_excepciones_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    empleado_id = request.args.get("empleado_id", type=int)
    fecha_desde = (request.args.get("fecha_desde") or "").strip() or None
    fecha_hasta = (request.args.get("fecha_hasta") or "").strip() or None
    tipo = (request.args.get("tipo") or "").strip() or None
    anula_raw = (request.args.get("anula_horario") or "").strip()
    anula_horario = None
    if anula_raw == "1":
        anula_horario = 1
    elif anula_raw == "0":
        anula_horario = 0
    orden = (request.args.get("orden") or "").strip() or "fecha_desc"
    if orden not in {"fecha_desc", "fecha_asc", "empleado_asc", "empleado_desc"}:
        orden = "fecha_desc"
    excepciones = get_all(
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo=tipo,
        anula_horario=anula_horario,
        order_by=orden,
    )
    empleados = get_empleados(include_inactive=True)
    return render_template(
        "empleado_excepciones/listado.html",
        excepciones=excepciones,
        empleados=empleados,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde or "",
        fecha_hasta=fecha_hasta or "",
        tipo=tipo or "",
        anula_horario=anula_raw,
        orden=orden,
        tipos=TIPOS,
    )


@empleado_excepciones_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        empleado = get_empleado_by_id(data.get("empleado_id")) if data.get("empleado_id") else None
        if not empleado:
            errors.append("Empleado invalido.")

        bloques = []
        try:
            bloques = _parse_bloques_json(data.get("bloques_json"))
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

        if data.get("tipo") == "CAMBIO_HORARIO" and not bloques:
            errors.append("CAMBIO_HORARIO requiere bloques.")

        if errors:
            return render_template(
                "empleado_excepciones/form.html",
                mode="new",
                data=data,
                errors=errors,
                empleados=empleados,
                tipos=TIPOS,
            )

        data["empresa_id"] = empleado.get("empresa_id")
        data["anula_horario"] = bool(data.get("anula_horario")) or (data.get("tipo") in TIPOS_ANULA)
        exc_id = create_excepcion(data, bloques)
        log_audit(session, "create", "empleado_excepciones", exc_id)
        return redirect(url_for("empleado_excepciones.listado"))

    return render_template(
        "empleado_excepciones/form.html",
        mode="new",
        data={"bloques_json": "[]"},
        empleados=empleados,
        tipos=TIPOS,
    )


@empleado_excepciones_bp.route("/editar/<int:excepcion_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(excepcion_id):
    excepcion = get_by_id(excepcion_id)
    if not excepcion:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract(request.form)
        empleado = get_empleado_by_id(data.get("empleado_id")) if data.get("empleado_id") else None
        if not empleado:
            errors.append("Empleado invalido.")

        bloques = []
        try:
            bloques = _parse_bloques_json(data.get("bloques_json"))
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

        if data.get("tipo") == "CAMBIO_HORARIO" and not bloques:
            errors.append("CAMBIO_HORARIO requiere bloques.")

        if errors:
            merged = dict(excepcion)
            merged.update(data)
            return render_template(
                "empleado_excepciones/form.html",
                mode="edit",
                data=merged,
                errors=errors,
                empleados=empleados,
                tipos=TIPOS,
            )

        data["empresa_id"] = empleado.get("empresa_id")
        data["anula_horario"] = bool(data.get("anula_horario")) or (data.get("tipo") in TIPOS_ANULA)
        update_excepcion(excepcion_id, data, bloques)
        log_audit(session, "update", "empleado_excepciones", excepcion_id)
        return redirect(url_for("empleado_excepciones.listado"))

    prefilled = dict(excepcion)
    prefilled["bloques_json"] = _serialize_excepcion_bloques(excepcion_id)
    return render_template(
        "empleado_excepciones/form.html",
        mode="edit",
        data=prefilled,
        empleados=empleados,
        tipos=TIPOS,
    )


@empleado_excepciones_bp.route("/eliminar/<int:excepcion_id>", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar(excepcion_id):
    delete(excepcion_id)
    log_audit(session, "delete", "empleado_excepciones", excepcion_id)
    return redirect(url_for("empleado_excepciones.listado"))


@empleado_excepciones_bp.route("/api/<int:excepcion_id>", methods=["GET"])
@role_required("admin", "rrhh")
def api_get(excepcion_id):
    excepcion = get_by_id(excepcion_id)
    if not excepcion:
        return jsonify({"error": "Excepcion no encontrada"}), 404
    bloques = json.loads(_serialize_excepcion_bloques(excepcion_id))
    payload = dict(excepcion)
    payload["bloques"] = bloques
    return jsonify(payload)


@empleado_excepciones_bp.route("/api", methods=["POST"])
@role_required("admin", "rrhh")
def api_create():
    payload = request.get_json(silent=True) or {}
    try:
        empleado_id = int(payload.get("empleado_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "empleado_id invalido"}), 400

    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        return jsonify({"error": "Empleado no encontrado"}), 404

    tipo = str(payload.get("tipo") or "").strip()
    data = {
        "empresa_id": empleado.get("empresa_id"),
        "empleado_id": empleado_id,
        "fecha": str(payload.get("fecha") or "").strip(),
        "tipo": tipo,
        "descripcion": str(payload.get("descripcion") or "").strip(),
        "anula_horario": bool(payload.get("anula_horario")) or (tipo in TIPOS_ANULA),
    }
    bloques = payload.get("bloques") or []
    try:
        exc_id = create_excepcion(data, bloques)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    log_audit(session, "create", "empleado_excepciones", exc_id)
    return jsonify({"id": exc_id}), 201


@empleado_excepciones_bp.route("/api/<int:excepcion_id>", methods=["PUT"])
@role_required("admin", "rrhh")
def api_update(excepcion_id):
    original = get_by_id(excepcion_id)
    if not original:
        return jsonify({"error": "Excepcion no encontrada"}), 404

    payload = request.get_json(silent=True) or {}
    try:
        empleado_id = int(payload.get("empleado_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "empleado_id invalido"}), 400
    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        return jsonify({"error": "Empleado no encontrado"}), 404

    tipo = str(payload.get("tipo") or "").strip()
    data = {
        "empresa_id": empleado.get("empresa_id"),
        "empleado_id": empleado_id,
        "fecha": str(payload.get("fecha") or "").strip(),
        "tipo": tipo,
        "descripcion": str(payload.get("descripcion") or "").strip(),
        "anula_horario": bool(payload.get("anula_horario")) or (tipo in TIPOS_ANULA),
    }
    bloques = payload.get("bloques") or []
    try:
        update_excepcion(excepcion_id, data, bloques)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    log_audit(session, "update", "empleado_excepciones", excepcion_id)
    return jsonify({"ok": True})

