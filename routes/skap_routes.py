from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.skap_pregunta_repository import get_all_active_for_sector
from repositories.skap_repository import (
    get_evaluacion_by_id,
    get_evaluacion_detalles,
    get_historial_empleado,
    get_plan_actions,
    get_plan_by_evaluacion_id,
    get_plan_by_empleado_anio,
)
from services.skap_service import (
    can_evaluate_employee,
    create_evaluacion,
    ensure_plan_for_evaluacion,
    get_mi_desarrollo,
    get_personal_ranking,
    get_preguntas_catalogo,
    get_preguntas_por_sector,
    serialize_evaluacion,
    serialize_pregunta,
    serialize_plan,
)
from utils.jwt_guard import INVALID_SESSION_MESSAGE, mobile_auth_required

skap_bp = Blueprint("skap", __name__, url_prefix="/api/skap")


def _ok(data=None, **extra):
    body = {"success": True}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return jsonify(body), 200


def _err(message: str, code: int = 400):
    return jsonify({"success": False, "error": message}), code


def _to_int(value, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        parsed = int(value)
        return parsed
    except (TypeError, ValueError):
        return default


def _current_employee():
    empleado_id = _to_int(getattr(g, "mobile_empleado_id", None))
    if not empleado_id:
        return None
    empleado = get_empleado_by_id(empleado_id)
    if not empleado or not empleado.get("activo"):
        return None
    return empleado


def _sector_from_request(args, empleado):
    sector_id = _to_int(args.get("sector_id"))
    if sector_id:
        return sector_id
    target_empleado_id = _to_int(args.get("empleado_id"))
    if target_empleado_id:
        target = get_empleado_by_id(target_empleado_id)
        if target and target.get("sector_id"):
            return _to_int(target.get("sector_id"))
    if empleado and empleado.get("sector_id"):
        return _to_int(empleado.get("sector_id"))
    return None


def _puesto_from_request(args, empleado):
    puesto_id = _to_int(args.get("puesto_id"))
    if puesto_id:
        return puesto_id
    target_empleado_id = _to_int(args.get("empleado_id"))
    if target_empleado_id:
        target = get_empleado_by_id(target_empleado_id)
        if target and target.get("puesto_id"):
            return _to_int(target.get("puesto_id"))
    if empleado and empleado.get("puesto_id"):
        return _to_int(empleado.get("puesto_id"))
    return None


@skap_bp.get("/preguntas")
@mobile_auth_required
def preguntas():
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    sector_id = _sector_from_request(request.args, empleado)
    if not sector_id:
        return _err("El sector es requerido para obtener las preguntas.", 400)
    puesto_id = _puesto_from_request(request.args, empleado)

    categoria = (request.args.get("categoria") or "").strip().upper() or None
    activo_raw = (request.args.get("activo") or "1").strip().lower()
    activo = None
    if activo_raw in {"1", "true", "si", "yes", "on"}:
        activo = 1
    elif activo_raw in {"0", "false", "no", "off"}:
        activo = 0

    rows = get_all_active_for_sector(sector_id, puesto_id=puesto_id, categoria=categoria, activo=activo)
    return _ok(
        {
            "sector_id": sector_id,
            "puesto_id": puesto_id,
            "items": [serialize_pregunta(row) for row in rows],
            "total": len(rows),
        }
    )


@skap_bp.post("/evaluacion")
@mobile_auth_required
def crear_evaluacion():
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    body = request.get_json(silent=True) or {}
    target_empleado_id = _to_int(body.get("empleado_id")) or int(empleado["id"])
    respuestas = body.get("respuestas")
    if not isinstance(respuestas, list):
        return _err("respuestas debe ser una lista.", 400)

    try:
        result = create_evaluacion(
            empleado_id=target_empleado_id,
            evaluador_empleado_id=int(empleado["id"]),
            evaluador_usuario_id=None,
            anio=_to_int(body.get("anio")),
            respuestas=respuestas,
            observaciones_generales=str(body.get("observaciones_generales") or "").strip() or None,
        )
        return _ok(result, message="Evaluacion creada correctamente.")
    except ValueError as exc:
        message = str(exc)
        code = 400
        if "permiso" in message.lower():
            code = 403
        elif "encontrada" in message.lower():
            code = 404
        elif "anio" in message.lower():
            code = 400
        elif "ya tiene" in message.lower():
            code = 409
        return _err(message, code)
    except Exception:
        current_app.logger.exception("skap_create_evaluacion_error", extra={"extra": {"empleado_id": empleado.get("id")}})
        return _err("No se pudo crear la evaluacion.", 500)


@skap_bp.get("/evaluacion/<int:evaluacion_id>")
@mobile_auth_required
def detalle_evaluacion(evaluacion_id: int):
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    evaluacion = get_evaluacion_by_id(evaluacion_id)
    if not evaluacion:
        return _err("Evaluacion no encontrada.", 404)

    if int(empleado["id"]) not in {int(evaluacion.get("empleado_id") or 0), int(evaluacion.get("evaluador_empleado_id") or 0)}:
        if not can_evaluate_employee(int(empleado["id"]), int(evaluacion.get("empleado_id") or 0)):
            return _err("No tiene permisos para ver esta evaluacion.", 403)

    detalles = get_evaluacion_detalles(evaluacion_id)
    plan = get_plan_by_evaluacion_id(evaluacion_id)
    acciones = get_plan_actions(int(plan["id"])) if plan else []
    return _ok(
        {
            "evaluacion": serialize_evaluacion(evaluacion, detalles=detalles, plan=plan),
            "plan": serialize_plan(plan, acciones) if plan else None,
        }
    )


@skap_bp.get("/mi_desarrollo")
@mobile_auth_required
def mi_desarrollo():
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    anio = _to_int(request.args.get("anio"))
    payload = get_mi_desarrollo(empleado_id=int(empleado["id"]), anio=anio)
    return _ok(payload)


@skap_bp.get("/ranking")
@mobile_auth_required
def ranking():
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    anio = _to_int(request.args.get("anio"))
    payload = get_personal_ranking(empleado_id=int(empleado["id"]), anio=anio)
    return _ok(payload)


@skap_bp.get("/planes")
@mobile_auth_required
def planes():
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    historial = get_historial_empleado(int(empleado["id"]), empresa_id=empleado.get("empresa_id"))
    selected_year = _to_int(request.args.get("anio"))
    if not selected_year:
        selected_year = int(historial[0]["anio"]) if historial else None

    items = []
    current_plan = None
    for row in historial:
        anio = int(row.get("anio") or 0)
        plan = get_plan_by_empleado_anio(int(empleado["id"]), anio, empresa_id=empleado.get("empresa_id"))
        if not plan:
            continue
        acciones = get_plan_actions(int(plan["id"]))
        serializado = serialize_plan(plan, acciones)
        items.append(serializado)
        if selected_year and anio == selected_year:
            current_plan = serializado

    if selected_year and not current_plan:
        plan = get_plan_by_empleado_anio(int(empleado["id"]), selected_year, empresa_id=empleado.get("empresa_id"))
        if plan:
            acciones = get_plan_actions(int(plan["id"]))
            current_plan = serialize_plan(plan, acciones)
            if all(int(item.get("anio") or 0) != selected_year for item in items):
                items.insert(0, current_plan)

    return _ok(
        {
            "anio_seleccionado": selected_year,
            "total": len(items),
            "items": sorted(items, key=lambda row: int(row.get("anio") or 0), reverse=True),
            "current": current_plan,
        }
    )


@skap_bp.post("/planes")
@mobile_auth_required
def crear_o_actualizar_plan():
    empleado = _current_employee()
    if not empleado:
        return _err(INVALID_SESSION_MESSAGE, 401)

    body = request.get_json(silent=True) or {}
    evaluacion_id = _to_int(body.get("evaluacion_id"))
    if not evaluacion_id:
        return _err("evaluacion_id es requerido.", 400)

    evaluacion = get_evaluacion_by_id(evaluacion_id)
    if not evaluacion:
        return _err("Evaluacion no encontrada.", 404)

    if int(empleado["id"]) not in {int(evaluacion.get("empleado_id") or 0), int(evaluacion.get("evaluador_empleado_id") or 0)}:
        if not can_evaluate_employee(int(empleado["id"]), int(evaluacion.get("empleado_id") or 0)):
            return _err("No tiene permisos para administrar este PDP.", 403)

    acciones = body.get("acciones")
    if acciones is not None and not isinstance(acciones, list):
        return _err("acciones debe ser una lista si se envian.", 400)

    try:
        plan = ensure_plan_for_evaluacion(evaluacion_id, acciones_extra=acciones)
        return _ok({"plan": plan}, message="Plan actualizado correctamente.")
    except ValueError as exc:
        message = str(exc)
        code = 400 if "encontrada" not in message.lower() else 404
        return _err(message, code)
    except Exception:
        current_app.logger.exception("skap_plan_upsert_error", extra={"extra": {"evaluacion_id": evaluacion_id}})
        return _err("No se pudo actualizar el plan de desarrollo.", 500)
