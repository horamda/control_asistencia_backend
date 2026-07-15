from __future__ import annotations

import datetime as _dt

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from repositories.empleado_repository import get_all as get_empleados
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.puesto_repository import get_all as get_puestos
from repositories.sector_repository import get_page as get_sectores_page
from repositories.skap_pregunta_repository import (
    count_all as count_preguntas,
    get_by_id as get_pregunta_by_id,
    get_page as get_preguntas_page,
)
from repositories.skap_repository import (
    add_plan_action,
    delete_plan_action,
    get_dashboard_summary,
    get_evaluacion_by_id,
    get_evaluacion_detalles,
    get_evaluaciones_page,
    get_historial_empleado,
    get_plan_action_by_id,
    get_plan_actions,
    get_plan_by_evaluacion_id,
    get_plan_by_id,
    get_planes_page,
    set_plan_action_estado,
    update_plan_action,
)
from services.skap_seed_service import importar_preguntas_desde_csv
from services.skap_service import (
    activar_pregunta,
    contar_preguntas,
    crear_pregunta,
    get_dashboard_data,
    get_evaluacion_detalle_pack,
    get_preguntas_catalogo,
    serialize_evaluacion,
    serialize_plan,
    actualizar_pregunta,
)
from utils.audit import log_audit
from web.auth.decorators import role_required

skap_web_bp = Blueprint("skap_web", __name__, url_prefix="/skap")

_CATEGORIAS = [
    ("S", "Skills"),
    ("K", "Knowledge"),
    ("A", "Attitude"),
    ("P", "Performance"),
]


def _parse_int(value, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        parsed = int(value)
        return parsed
    except (TypeError, ValueError):
        return default


def _parse_bool(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "on"}


def _parse_date(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            return _dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _current_role():
    return (session.get("user_role") or session.get("role") or "").strip().lower()


def _sector_options(include_inactive: bool = True):
    rows, _ = get_sectores_page(1, 500, activo=None if include_inactive else 1)
    return rows


def _employee_options(include_inactive: bool = False):
    return get_empleados(include_inactive=include_inactive)


def _puesto_options(include_inactive: bool = True):
    return get_puestos(include_inactive=include_inactive)


def _pregunta_form_from_request(form) -> dict:
    return {
        "sector_id": _parse_int(form.get("sector_id")),
        "puesto_id": _parse_int(form.get("puesto_id")),
        "categoria": (form.get("categoria") or "").strip().upper(),
        "descripcion": (form.get("descripcion") or "").strip(),
        "peso": float(form.get("peso") or 1),
        "puntaje_esperado": _parse_int(form.get("puntaje_esperado"), 4),
        "requiere_observacion": _parse_bool(form.get("requiere_observacion")),
        "requiere_evidencia": _parse_bool(form.get("requiere_evidencia")),
        "activo": _parse_bool(form.get("activo", "1")),
    }


def _action_form_from_request(form) -> dict:
    estado = (form.get("estado") or "pendiente").strip().lower()
    data = {
        "categoria": (form.get("categoria") or "").strip().upper() or None,
        "accion": (form.get("accion") or "").strip(),
        "responsable_empleado_id": _parse_int(form.get("responsable_empleado_id")),
        "fecha_compromiso": _parse_date(form.get("fecha_compromiso")),
        "estado": estado,
        "comentarios": (form.get("comentarios") or "").strip() or None,
        "completado_at": None,
    }
    if estado == "completado":
        data["completado_at"] = _dt.datetime.now().replace(microsecond=0)
    if estado == "cancelado":
        data["completado_at"] = None
    return data


@skap_web_bp.route("/")
@role_required("admin", "rrhh", "supervisor")
def dashboard():
    anio = _parse_int(request.args.get("anio"), _dt.date.today().year) or _dt.date.today().year
    sector_id = _parse_int(request.args.get("sector_id"))
    data = get_dashboard_data(anio=anio, sector_id=sector_id)
    return render_template(
        "skap/dashboard.html",
        data=data,
        anio=anio,
        sector_id=sector_id,
        sectores=_sector_options(),
        current_role=_current_role(),
        error=(request.args.get("error") or "").strip() or None,
        msg=(request.args.get("msg") or "").strip() or None,
    )


@skap_web_bp.route("/preguntas")
@role_required("admin", "rrhh")
def preguntas_listado():
    page = max(1, _parse_int(request.args.get("page"), 1) or 1)
    per_page = max(1, min(_parse_int(request.args.get("per"), 20) or 20, 100))
    search = (request.args.get("q") or "").strip() or None
    sector_id = _parse_int(request.args.get("sector_id"))
    puesto_raw = (request.args.get("puesto_id") or "").strip()
    puesto_filter = _parse_int(puesto_raw) if puesto_raw else None
    categoria = (request.args.get("categoria") or "").strip().upper() or None
    activo_raw = (request.args.get("activo") or "").strip().lower()
    activo = None
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    preguntas, total = get_preguntas_catalogo(
        page=page,
        per_page=per_page,
        search=search,
        sector_id=sector_id,
        puesto_filter=puesto_filter,
        categoria=categoria,
        activo=activo,
    )
    return render_template(
        "skap/preguntas_listado.html",
        preguntas=preguntas,
        total=total,
        page=page,
        per_page=per_page,
        q=search or "",
        sector_id=sector_id,
        puesto_id=puesto_raw,
        categorias=_CATEGORIAS,
        categoria=categoria or "",
        activo=activo_raw or "all",
        sectores=_sector_options(),
        puestos=_puesto_options(),
        error=(request.args.get("error") or "").strip() or None,
        msg=(request.args.get("msg") or "").strip() or None,
    )


@skap_web_bp.route("/preguntas/nueva", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def pregunta_nueva():
    data = {"activo": True, "puntaje_esperado": 4, "peso": 1}
    errors = []
    if request.method == "POST":
        data = _pregunta_form_from_request(request.form)
        try:
            pregunta_id = crear_pregunta(data)
            log_audit(session, "create", "skap_preguntas", pregunta_id)
            return redirect(url_for("skap_web.preguntas_listado", msg="Pregunta creada."))
        except ValueError as exc:
            errors.append(str(exc))
        except Exception:
            current_app.logger.exception("skap_pregunta_create_error")
            errors.append("No se pudo crear la pregunta.")
    return render_template(
        "skap/pregunta_form.html",
        mode="new",
        data=data,
        errors=errors,
        sectores=_sector_options(),
        puestos=_puesto_options(),
        categorias=_CATEGORIAS,
    )


@skap_web_bp.route("/preguntas/editar/<int:pregunta_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def pregunta_editar(pregunta_id: int):
    pregunta = get_pregunta_by_id(pregunta_id)
    if not pregunta:
        return redirect(url_for("skap_web.preguntas_listado", error="Pregunta no encontrada."))
    data = dict(pregunta)
    errors = []
    if request.method == "POST":
        data = _pregunta_form_from_request(request.form)
        try:
            actualizar_pregunta(pregunta_id, data)
            log_audit(session, "update", "skap_preguntas", pregunta_id)
            return redirect(url_for("skap_web.preguntas_listado", msg="Pregunta actualizada."))
        except ValueError as exc:
            errors.append(str(exc))
        except Exception:
            current_app.logger.exception("skap_pregunta_update_error")
            errors.append("No se pudo actualizar la pregunta.")
    return render_template(
        "skap/pregunta_form.html",
        mode="edit",
        data=data,
        errors=errors,
        sectores=_sector_options(),
        puestos=_puesto_options(),
        categorias=_CATEGORIAS,
    )


@skap_web_bp.post("/preguntas/activar/<int:pregunta_id>")
@role_required("admin", "rrhh")
def pregunta_activar(pregunta_id: int):
    try:
        activar_pregunta(pregunta_id, 1)
        log_audit(session, "activate", "skap_preguntas", pregunta_id)
    except Exception:
        current_app.logger.exception("skap_pregunta_activate_error")
    return redirect(url_for("skap_web.preguntas_listado"))


@skap_web_bp.post("/preguntas/desactivar/<int:pregunta_id>")
@role_required("admin", "rrhh")
def pregunta_desactivar(pregunta_id: int):
    try:
        activar_pregunta(pregunta_id, 0)
        log_audit(session, "deactivate", "skap_preguntas", pregunta_id)
    except Exception:
        current_app.logger.exception("skap_pregunta_deactivate_error")
    return redirect(url_for("skap_web.preguntas_listado"))


@skap_web_bp.route("/preguntas/importar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def preguntas_importar():
    resultado = None
    reactivate = _parse_bool(request.form.get("reactivate")) if request.method == "POST" else False
    if request.method == "POST":
        archivo = request.files.get("archivo_csv")
        if not archivo or not str(archivo.filename or "").lower().endswith(".csv"):
            resultado = {"error": "Debe subir un archivo .csv valido."}
        else:
            try:
                resultado = importar_preguntas_desde_csv(archivo.stream, reactivate=reactivate)
                log_audit(session, "importar_csv", "skap_preguntas", 0)
            except Exception as exc:
                current_app.logger.exception("skap_preguntas_import_error")
                resultado = {"error": f"No se pudo procesar el archivo: {exc}"}
    return render_template("skap/preguntas_importar.html", resultado=resultado, reactivate=reactivate)


@skap_web_bp.route("/evaluaciones")
@role_required("admin", "rrhh", "supervisor")
def evaluaciones_listado():
    page = max(1, _parse_int(request.args.get("page"), 1) or 1)
    per_page = max(1, min(_parse_int(request.args.get("per"), 20) or 20, 100))
    anio = _parse_int(request.args.get("anio"))
    sector_id = _parse_int(request.args.get("sector_id"))
    search = (request.args.get("q") or "").strip() or None
    rows, total = get_evaluaciones_page(
        page,
        per_page,
        anio=anio,
        sector_id=sector_id,
        search=search,
    )
    return render_template(
        "skap/evaluaciones_listado.html",
        evaluaciones=rows,
        total=total,
        page=page,
        per_page=per_page,
        anio=anio or "",
        sector_id=sector_id,
        q=search or "",
        sectores=_sector_options(),
        error=(request.args.get("error") or "").strip() or None,
        msg=(request.args.get("msg") or "").strip() or None,
    )


@skap_web_bp.route("/evaluaciones/<int:evaluacion_id>")
@role_required("admin", "rrhh", "supervisor")
def evaluacion_detalle(evaluacion_id: int):
    try:
        evaluacion, detalles, _plan = get_evaluacion_detalle_pack(evaluacion_id)
    except ValueError as exc:
        return redirect(url_for("skap_web.evaluaciones_listado", error=str(exc)))
    if not evaluacion:
        return redirect(url_for("skap_web.evaluaciones_listado", error="Evaluacion no encontrada."))
    return render_template(
        "skap/evaluacion_detalle.html",
        evaluacion=serialize_evaluacion(evaluacion, detalles=detalles, plan=get_plan_by_evaluacion_id(evaluacion_id)),
        plan=_plan,
        current_role=_current_role(),
        error=(request.args.get("error") or "").strip() or None,
        msg=(request.args.get("msg") or "").strip() or None,
    )


@skap_web_bp.route("/planes")
@role_required("admin", "rrhh", "supervisor")
def planes_listado():
    page = max(1, _parse_int(request.args.get("page"), 1) or 1)
    per_page = max(1, min(_parse_int(request.args.get("per"), 20) or 20, 100))
    anio = _parse_int(request.args.get("anio"))
    sector_id = _parse_int(request.args.get("sector_id"))
    search = (request.args.get("q") or "").strip() or None
    rows, total = get_planes_page(
        page,
        per_page,
        anio=anio,
        sector_id=sector_id,
        search=search,
    )
    return render_template(
        "skap/planes_listado.html",
        planes=rows,
        total=total,
        page=page,
        per_page=per_page,
        anio=anio or "",
        sector_id=sector_id,
        q=search or "",
        sectores=_sector_options(),
        error=(request.args.get("error") or "").strip() or None,
        msg=(request.args.get("msg") or "").strip() or None,
    )


@skap_web_bp.route("/planes/<int:plan_id>")
@role_required("admin", "rrhh", "supervisor")
def plan_detalle(plan_id: int):
    plan = get_plan_by_id(plan_id)
    if not plan:
        return redirect(url_for("skap_web.planes_listado", error="Plan no encontrado."))
    acciones = get_plan_actions(plan_id)
    edit_action_id = _parse_int(request.args.get("edit_action"))
    edit_action = get_plan_action_by_id(edit_action_id) if edit_action_id else None
    return render_template(
        "skap/plan_detalle.html",
        plan=serialize_plan(plan, acciones),
        acciones=acciones,
        edit_action=edit_action,
        empleados=_employee_options(),
        categorias=_CATEGORIAS,
        error=(request.args.get("error") or "").strip() or None,
        msg=(request.args.get("msg") or "").strip() or None,
    )


@skap_web_bp.post("/planes/<int:plan_id>/acciones")
@role_required("admin", "rrhh", "supervisor")
def plan_accion_nueva(plan_id: int):
    plan = get_plan_by_id(plan_id)
    if not plan:
        return redirect(url_for("skap_web.planes_listado", error="Plan no encontrado."))
    data = _action_form_from_request(request.form)
    data["plan_id"] = plan_id
    try:
        if not data["accion"]:
            raise ValueError("La accion es obligatoria.")
        action_id = add_plan_action(data)
        log_audit(session, "create", "skap_planes_desarrollo_acciones", action_id)
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, msg="Accion creada."))
    except Exception as exc:
        current_app.logger.exception("skap_action_create_error")
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, error=str(exc)))


@skap_web_bp.post("/planes/<int:plan_id>/acciones/<int:action_id>/editar")
@role_required("admin", "rrhh", "supervisor")
def plan_accion_editar(plan_id: int, action_id: int):
    action = get_plan_action_by_id(action_id)
    if not action or int(action.get("plan_id") or 0) != int(plan_id):
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, error="Accion no encontrada."))
    data = _action_form_from_request(request.form)
    data["plan_id"] = plan_id
    try:
        if not data["accion"]:
            raise ValueError("La accion es obligatoria.")
        update_plan_action(action_id, data)
        log_audit(session, "update", "skap_planes_desarrollo_acciones", action_id)
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, msg="Accion actualizada."))
    except Exception as exc:
        current_app.logger.exception("skap_action_update_error")
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, edit_action=action_id, error=str(exc)))


@skap_web_bp.post("/planes/<int:plan_id>/acciones/<int:action_id>/estado")
@role_required("admin", "rrhh", "supervisor")
def plan_accion_estado(plan_id: int, action_id: int):
    estado = (request.form.get("estado") or "").strip().lower()
    if estado not in {"pendiente", "en_proceso", "completado", "cancelado"}:
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, error="Estado invalido."))
    completado_at = _dt.datetime.now().replace(microsecond=0) if estado == "completado" else None
    try:
        set_plan_action_estado(action_id, estado, completado_at=completado_at)
        log_audit(session, "update", "skap_planes_desarrollo_acciones", action_id)
    except Exception:
        current_app.logger.exception("skap_action_state_error")
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, error="No se pudo actualizar la accion."))
    return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, msg="Estado actualizado."))


@skap_web_bp.post("/planes/<int:plan_id>/acciones/<int:action_id>/eliminar")
@role_required("admin", "rrhh", "supervisor")
def plan_accion_eliminar(plan_id: int, action_id: int):
    try:
        delete_plan_action(action_id)
        log_audit(session, "delete", "skap_planes_desarrollo_acciones", action_id)
    except Exception:
        current_app.logger.exception("skap_action_delete_error")
        return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, error="No se pudo eliminar la accion."))
    return redirect(url_for("skap_web.plan_detalle", plan_id=plan_id, msg="Accion eliminada."))
