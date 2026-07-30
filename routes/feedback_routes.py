from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.feedback_cliente_repository import get_page as get_clientes_page
from repositories.feedback_motivo_repository import get_all as get_motivos_activos
from services.feedback_service import (
    create_feedback,
    get_feedback_bandeja,
    get_feedback_dashboard,
    get_feedback_historial,
    resolver_feedback,
    serialize_feedback,
    tomar_feedback,
)
from utils.jwt_guard import INVALID_SESSION_MESSAGE, mobile_auth_required

feedback_bp = Blueprint("feedback", __name__, url_prefix="/api/v1/feedback")


def _current_employee():
    empleado_id = int(g.mobile_empleado_id)
    empleado = get_empleado_by_id(empleado_id)
    if not empleado or not empleado.get("activo"):
        return None
    return empleado


def _to_int(value, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _nullable_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _search_arg(*names: str) -> str | None:
    for name in names:
        value = (request.args.get(name) or "").strip()
        if value:
            return value
    return None


@feedback_bp.get("/motivos")
@mobile_auth_required
def motivos():
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    items = [
        {
            "id": row.get("id"),
            "nombre": row.get("nombre"),
            "descripcion": row.get("descripcion"),
            "sector_responsable_id": row.get("sector_id"),
            "sector_responsable_nombre": row.get("sector_nombre"),
            "tiempo_resolucion_valor": int(row.get("tiempo_resolucion_valor") or row.get("sla_dias") or 0),
            "tiempo_resolucion_unidad": row.get("tiempo_resolucion_unidad") or "DIAS",
            "sla_dias": int(row.get("sla_dias") or 0),
            "requiere_foto": bool(row.get("requiere_foto")),
            "requiere_observacion": bool(row.get("requiere_observacion", True)),
        }
        for row in get_motivos_activos(include_inactive=False)
    ]
    return jsonify({"items": items, "total": len(items)})


@feedback_bp.get("/clientes")
@mobile_auth_required
def clientes():
    q = _search_arg(
        "q",
        "search",
        "query",
        "cliente_q",
        "cliente",
        "razon_social",
        "razonSocial",
        "nombre_fantasia",
        "nombreFantasia",
        "nombre",
    )
    page = _to_int(request.args.get("page"), 1)
    per_page = min(_to_int(request.args.get("per_page"), 20), 200)
    rows, total = get_clientes_page(page, per_page, search=q, activo=1)
    items = [
        {
            "id": row.get("id"),
            "codigo": row.get("codigo_externo"),
            "sucursal_origen": _nullable_int(row.get("sucursal_origen")),
            "razon_social": row.get("razon_social"),
            "nombre_fantasia": row.get("nombre_fantasia"),
            "telefonos": row.get("telefonos"),
            "movil": row.get("movil"),
            "email": row.get("email"),
            "domicilio": row.get("domicilio"),
            "localidad": row.get("localidad"),
            "provincia": row.get("provincia"),
            "tipo": row.get("tipo_descripcion"),
        }
        for row in rows
    ]
    return jsonify({"items": items, "page": page, "per_page": per_page, "total": total})


@feedback_bp.get("/historial")
@mobile_auth_required
def historial():
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    page = _to_int(request.args.get("page"), 1)
    per_page = min(_to_int(request.args.get("per_page"), 20), 50)
    estado = (request.args.get("estado") or "").strip() or None
    search = (request.args.get("q") or "").strip() or None
    items, total = get_feedback_historial(
        empleado_id=int(empleado["id"]),
        sector_origen_id=_nullable_int(empleado.get("sector_id")),
        page=page,
        per_page=per_page,
        estado=estado,
        search=search,
    )
    return jsonify({"items": items, "page": page, "per_page": per_page, "total": total})


@feedback_bp.get("/bandeja")
@mobile_auth_required
def bandeja():
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    page = _to_int(request.args.get("page"), 1)
    per_page = min(_to_int(request.args.get("per_page"), 20), 50)
    estado = (request.args.get("estado") or "").strip() or None
    search = (request.args.get("q") or "").strip() or None
    items, total = get_feedback_bandeja(
        jefe_directo_id=int(empleado["id"]),
        page=page,
        per_page=per_page,
        estado=estado,
        search=search,
    )
    return jsonify({"items": items, "page": page, "per_page": per_page, "total": total})


@feedback_bp.get("/dashboard")
@mobile_auth_required
def dashboard():
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    empresa_id = int(empleado.get("empresa_id") or 0) or None
    sector_id = int(empleado.get("sector_id") or 0) or None
    payload = get_feedback_dashboard(
        empresa_id=empresa_id,
        sector_id=sector_id,
        empleado_id=int(empleado["id"]),
    )
    payload["empleado"] = {
        "id": empleado.get("id"),
        "nombre": empleado.get("nombre"),
        "apellido": empleado.get("apellido"),
        "legajo": empleado.get("legajo"),
        "empresa_id": empleado.get("empresa_id"),
    }
    return jsonify(payload)


@feedback_bp.post("")
@mobile_auth_required
def crear():
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    body = request.get_json(silent=True) if request.is_json else request.form
    body = body or {}
    evidencia_file = (
        request.files.get("evidencia_file")
        or request.files.get("evidencia")
        or request.files.get("foto")
        or request.files.get("foto_file")
    )
    try:
        feedback_id = create_feedback(
            empleado_id=int(empleado["id"]),
            cliente_id=_to_int(body.get("cliente_id"), 0),
            motivo_id=_to_int(body.get("motivo_id"), 0),
            descripcion=str(body.get("descripcion") or "").strip(),
            evidencia_file=evidencia_file,
        )
    except ValueError as exc:
        message = str(exc)
        code = 400
        if "permiso" in message.lower():
            code = 403
        return jsonify({"error": message}), code
    except Exception:
        current_app.logger.exception("feedback_create_error", extra={"extra": {"empleado_id": empleado.get("id")}})
        return jsonify({"error": "No se pudo crear el feedback."}), 500

    from repositories.feedback_repository import get_by_id

    feedback = serialize_feedback(get_by_id(feedback_id))
    return jsonify({"ok": True, "feedback": feedback}), 201


@feedback_bp.get("/<int:feedback_id>")
@mobile_auth_required
def detalle(feedback_id: int):
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    from repositories.feedback_repository import get_by_id

    feedback = get_by_id(feedback_id)
    if not feedback:
        return jsonify({"error": "Feedback no encontrado."}), 404
    puede_ver_por_origen = int(feedback.get("sector_origen_id") or feedback.get("empleado_sector_id") or 0) == int(empleado.get("sector_id") or 0)
    puede_ver_por_responsable = int(feedback.get("responsable_id") or feedback.get("jefe_directo_id") or 0) == int(empleado["id"])
    if not puede_ver_por_origen and not puede_ver_por_responsable:
        return jsonify({"error": "No tiene permisos para ver este feedback."}), 403
    return jsonify({"feedback": serialize_feedback(feedback)})


@feedback_bp.post("/<int:feedback_id>/tomar")
@mobile_auth_required
def tomar(feedback_id: int):
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    try:
        tomar_feedback(feedback_id, actor_empleado_id=int(empleado["id"]))
        from repositories.feedback_repository import get_by_id

        return jsonify({"ok": True, "feedback": serialize_feedback(get_by_id(feedback_id))})
    except ValueError as exc:
        message = str(exc)
        code = 403 if "permiso" in message.lower() else 400
        if "no encontrado" in message.lower():
            code = 404
        return jsonify({"error": message}), code
    except Exception:
        current_app.logger.exception("feedback_tomar_error", extra={"extra": {"feedback_id": feedback_id}})
        return jsonify({"error": "No se pudo actualizar el feedback."}), 500


@feedback_bp.post("/<int:feedback_id>/resolver")
@mobile_auth_required
def resolver(feedback_id: int):
    empleado = _current_employee()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    body = request.get_json(silent=True) or {}
    try:
        resolver_feedback(
            feedback_id,
            actor_empleado_id=int(empleado["id"]),
            resolucion_descripcion=str(body.get("resolucion_descripcion") or "").strip(),
        )
        from repositories.feedback_repository import get_by_id

        return jsonify({"ok": True, "feedback": serialize_feedback(get_by_id(feedback_id))})
    except ValueError as exc:
        message = str(exc)
        code = 403 if "permiso" in message.lower() else 400
        if "no encontrado" in message.lower():
            code = 404
        return jsonify({"error": message}), code
    except Exception:
        current_app.logger.exception("feedback_resolver_error", extra={"extra": {"feedback_id": feedback_id}})
        return jsonify({"error": "No se pudo resolver el feedback."}), 500
