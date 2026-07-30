from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from repositories.feedback_cliente_repository import count_all as count_clientes
from repositories.feedback_cliente_repository import get_page as get_clientes_page
from repositories.empleado_repository import get_all as get_empleados
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.feedback_motivo_repository import (
    count_all as count_motivos,
    create as create_motivo,
    get_by_id as get_motivo_by_id,
    get_by_nombre as get_motivo_by_nombre,
    get_page as get_motivos_page,
    set_activo as set_motivo_activo,
    update as update_motivo,
    get_all as get_motivos,
)
from repositories.feedback_repository import get_by_id as get_feedback_by_id
from repositories.feedback_repository import get_page as get_feedbacks_page
from repositories.sector_repository import get_all as get_sectores
from repositories.sector_repository import get_ids_by_responsable_empleado
from repositories.sucursal_repository import get_all as get_sucursales
from services.feedback_import_service import importar_clientes_desde_csv
from services.feedback_service import (
    create_feedback,
    get_feedback_bandeja,
    get_feedback_dashboard,
    resolver_feedback_admin,
    resolver_feedback,
    serialize_feedback,
    tomar_feedback,
)
from utils.audit import log_audit
from web.auth.decorators import current_empleado_id, has_role, login_required, role_required

feedback_web_bp = Blueprint("feedback_web", __name__, url_prefix="/feedback")


def _parse_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _search_arg(*names: str) -> str | None:
    for name in names:
        value = (request.values.get(name) or "").strip()
        if value:
            return value
    return None


def _extract_motivo_form(form) -> dict:
    tiempo_valor = int(form.get("tiempo_resolucion_valor") or form.get("sla_dias") or 0)
    tiempo_unidad = (form.get("tiempo_resolucion_unidad") or "DIAS").strip().upper()
    if tiempo_unidad not in {"HORAS", "DIAS"}:
        tiempo_unidad = "DIAS"
    return {
        "nombre": (form.get("nombre") or "").strip(),
        "sector_id": _parse_int(form.get("sector_id")),
        "descripcion": (form.get("descripcion") or "").strip() or None,
        "sla_dias": tiempo_valor if tiempo_unidad == "DIAS" else max(1, (tiempo_valor + 23) // 24),
        "tiempo_resolucion_valor": tiempo_valor,
        "tiempo_resolucion_unidad": tiempo_unidad,
        "requiere_foto": str(form.get("requiere_foto") or "").strip() in {"1", "true", "on", "yes", "si"},
        "requiere_observacion": str(form.get("requiere_observacion") or "").strip() in {"1", "true", "on", "yes", "si"},
        "activo": str(form.get("activo") or "1").strip() in {"1", "true", "on", "yes", "si"},
    }


def _can_resolve_as_admin() -> bool:
    user_id = session.get("user_id")
    return bool(user_id and (has_role(user_id, "admin") or has_role(user_id, "rrhh")))


def _is_global_feedback_user() -> bool:
    return _can_resolve_as_admin()


def _current_feedback_scope() -> dict:
    if _is_global_feedback_user():
        return {"global": True, "empleado_id": current_empleado_id(), "sector_id": None, "empleado": None}

    empleado_id = current_empleado_id()
    if not empleado_id:
        return {
            "global": False,
            "empleado_id": None,
            "sector_id": None,
            "empleado": None,
            "error": "El usuario no tiene empleado vinculado para ver feedback por sector.",
        }

    empleado = get_empleado_by_id(empleado_id)
    sector_id = _parse_int((empleado or {}).get("sector_id"))
    if not empleado or not sector_id:
        return {
            "global": False,
            "empleado_id": empleado_id,
            "sector_id": None,
            "empleado": empleado,
            "error": "El empleado vinculado no tiene sector asignado.",
        }

    try:
        responsable_sector_ids = get_ids_by_responsable_empleado(empleado_id)
    except Exception:
        current_app.logger.warning("feedback_scope_responsable_sectores_error", exc_info=True)
        responsable_sector_ids = []

    return {
        "global": False,
        "empleado_id": empleado_id,
        "sector_id": sector_id,
        "responsable_sector_ids": responsable_sector_ids,
        "empleado": empleado,
    }


def _sector_visible_for_scope(row: dict, scope: dict) -> bool:
    if scope.get("global"):
        return True
    empleado_id = scope.get("empleado_id")
    if empleado_id and int(row.get("jefe_directo_id") or row.get("responsable_id") or 0) == int(empleado_id):
        return True
    if empleado_id and int(row.get("responsable_id") or row.get("jefe_directo_id") or 0) == int(empleado_id):
        return True
    sector_id = scope.get("sector_id")
    if sector_id and int(row.get("sector_origen_id") or row.get("empleado_sector_id") or 0) == int(sector_id):
        return True
    responsable_sector_ids = {int(value) for value in scope.get("responsable_sector_ids") or []}
    return bool(int(row.get("sector_responsable_id") or 0) in responsable_sector_ids)


def _can_respond_feedback_item(item: dict, actor_empleado_id: int | None) -> bool:
    if (item.get("estado_actual") or "pendiente") == "resuelto":
        return False
    if _can_resolve_as_admin():
        return True
    if not actor_empleado_id:
        return False
    return (
        int(item.get("jefe_directo", {}).get("id") or 0) == int(actor_empleado_id)
        or int(item.get("responsable", {}).get("id") or 0) == int(actor_empleado_id)
    )


@feedback_web_bp.route("/")
@role_required("admin", "rrhh", "supervisor", "jefe")
def dashboard():
    scope = _current_feedback_scope()
    sector_id = _parse_int(request.args.get("sector_id"))
    if not scope.get("global"):
        sector_id = scope.get("sector_id")
    sucursal_id = _parse_int(request.args.get("sucursal_id"))
    empleado_activo_raw = (request.args.get("empleado_activo") or "1").strip().lower()
    empleado_activo = None
    if empleado_activo_raw == "1":
        empleado_activo = 1
    elif empleado_activo_raw == "0":
        empleado_activo = 0
    else:
        empleado_activo_raw = "all"
    empleado_id = current_empleado_id()
    if scope.get("error"):
        datos = get_feedback_dashboard(sector_id=-1, empleado_id=empleado_id, empleado_activo=empleado_activo)
        bandeja_pendiente = 0
    else:
        datos = get_feedback_dashboard(
            sector_id=sector_id,
            sucursal_id=sucursal_id,
            empleado_id=empleado_id,
            empleado_activo=empleado_activo,
        )
        bandeja_pendiente = 0
        if empleado_id:
            _, bandeja_pendiente = get_feedback_bandeja(jefe_directo_id=empleado_id, page=1, per_page=1, estado="pendiente")
    return render_template(
        "feedback/dashboard.html",
        resumen=datos["resumen"],
        top_motivos=datos["top_motivos"],
        ranking=datos["ranking"],
        personal=datos.get("personal"),
        totales=datos.get("totales"),
        total_motivos=count_motivos(include_inactive=True),
        total_clientes=count_clientes(include_inactive=True),
        sectores=get_sectores(include_inactive=True),
        sucursales=get_sucursales(include_inactive=True),
        can_manage_feedback=scope.get("global"),
        scope_error=scope.get("error"),
        scope_sector_nombre=(scope.get("empleado") or {}).get("sector_nombre"),
        sector_id=sector_id,
        sucursal_id=sucursal_id,
        empleado_activo=empleado_activo_raw,
        tiene_empleado_vinculado=bool(empleado_id),
        bandeja_pendiente=bandeja_pendiente,
    )


@feedback_web_bp.route("/registros")
@role_required("admin", "rrhh", "supervisor", "jefe")
def registros_listado():
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per", 20, type=int) or 20, 100))
    scope = _current_feedback_scope()
    can_manage_feedback = bool(scope.get("global"))
    sector_id = _parse_int(request.args.get("sector_id"))
    if not can_manage_feedback:
        sector_id = scope.get("sector_id")
    sector_responsable_id = _parse_int(request.args.get("sector_responsable_id")) if can_manage_feedback else None
    sucursal_id = _parse_int(request.args.get("sucursal_id"))
    jefe_directo_id = _parse_int(request.args.get("jefe_directo_id")) if can_manage_feedback else None
    if not can_manage_feedback and _parse_int(request.args.get("jefe_directo_id")) == scope.get("empleado_id"):
        jefe_directo_id = scope.get("empleado_id")
        sector_id = None
    error = (request.args.get("error") or "").strip() or None
    blocked_by_missing_employee = False
    if scope.get("error"):
        rows, total = [], 0
        error = error or scope.get("error")
        blocked_by_missing_employee = True
    estado = (request.args.get("estado") or "").strip().lower() or None
    if estado not in {None, "pendiente", "resuelto", "vencido"}:
        estado = None
    activo_raw = (request.args.get("empleado_activo") or "all").strip().lower()
    empleado_activo = 1 if activo_raw == "1" else 0 if activo_raw == "0" else None
    activo_raw = activo_raw if activo_raw in {"1", "0"} else "all"
    search = (request.args.get("q") or "").strip() or None
    if not blocked_by_missing_employee:
        rows, total = get_feedbacks_page(
            page,
            per_page,
            estado=estado,
            search=search,
            sector_id=sector_id,
            sector_responsable_id=sector_responsable_id,
            sucursal_id=sucursal_id,
            jefe_directo_id=jefe_directo_id,
            empleado_activo=empleado_activo,
        )
    serialized_feedbacks = [serialize_feedback(row) for row in rows]
    actor_empleado_id = current_empleado_id()
    for item in serialized_feedbacks:
        item["puede_responder"] = _can_respond_feedback_item(item, actor_empleado_id)

    return render_template(
        "feedback/registros_listado.html",
        feedbacks=serialized_feedbacks,
        sectores=get_sectores(include_inactive=True),
        sucursales=get_sucursales(include_inactive=True),
        jefes=get_empleados(include_inactive=True) if can_manage_feedback else [],
        can_manage_feedback=can_manage_feedback,
        scope_sector_nombre=(scope.get("empleado") or {}).get("sector_nombre"),
        sector_id=sector_id,
        sucursal_id=sucursal_id,
        jefe_directo_id=jefe_directo_id,
        sector_responsable_id=sector_responsable_id,
        empleado_activo=activo_raw,
        estado=estado or "all",
        q=search or "",
        page=page,
        per_page=per_page,
        total=total,
        msg=(request.args.get("msg") or "").strip() or None,
        error=error,
    )


@feedback_web_bp.route("/bandeja")
@role_required("admin", "rrhh", "supervisor", "jefe")
def bandeja_jefe():
    empleado_id = current_empleado_id()
    if not empleado_id:
        return redirect(url_for("feedback_web.dashboard", error="El usuario no tiene empleado vinculado."))
    args = request.args.to_dict(flat=True)
    args["jefe_directo_id"] = empleado_id
    return redirect(url_for("feedback_web.registros_listado", **args))


@feedback_web_bp.route("/registros/<int:feedback_id>")
@role_required("admin", "rrhh", "supervisor", "jefe")
def registro_detalle(feedback_id: int):
    scope = _current_feedback_scope()
    row = get_feedback_by_id(feedback_id)
    if not row:
        return redirect(url_for("feedback_web.registros_listado", error="Feedback no encontrado."))
    if not _sector_visible_for_scope(row, scope):
        return redirect(url_for("feedback_web.registros_listado", error="No tiene permisos para ver este feedback."))
    item = serialize_feedback(row)
    actor_empleado_id = current_empleado_id()
    puede_responder = _can_respond_feedback_item(item, actor_empleado_id)
    return render_template(
        "feedback/registro_detalle.html",
        item=item,
        puede_responder=puede_responder,
        msg=(request.args.get("msg") or "").strip() or None,
        error=(request.args.get("error") or "").strip() or None,
    )


@feedback_web_bp.post("/registros/<int:feedback_id>/tomar")
@role_required("admin", "rrhh", "supervisor", "jefe")
def registro_tomar(feedback_id: int):
    actor_empleado_id = current_empleado_id()
    if not actor_empleado_id:
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, error="El usuario no tiene empleado vinculado para tomar el caso."))
    scope = _current_feedback_scope()
    try:
        row = get_feedback_by_id(feedback_id)
        if not row:
            raise ValueError("Feedback no encontrado.")
        if not _sector_visible_for_scope(row, scope):
            raise ValueError("No tiene permisos para tomar este feedback.")
        tomar_feedback(feedback_id, actor_empleado_id=actor_empleado_id)
        log_audit(session, "tomar", "feedbacks", feedback_id)
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, msg="Feedback tomado."))
    except ValueError as exc:
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, error=str(exc)))
    except Exception:
        current_app.logger.exception("feedback_web_tomar_error", extra={"extra": {"feedback_id": feedback_id}})
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, error="No se pudo tomar el feedback."))


@feedback_web_bp.post("/registros/<int:feedback_id>/resolver")
@role_required("admin", "rrhh", "supervisor", "jefe")
def registro_resolver(feedback_id: int):
    scope = _current_feedback_scope()
    actor_empleado_id = current_empleado_id()
    resolucion = (request.form.get("resolucion_descripcion") or "").strip()
    try:
        row = get_feedback_by_id(feedback_id)
        if not row:
            raise ValueError("Feedback no encontrado.")
        if not _sector_visible_for_scope(row, scope):
            raise ValueError("No tiene permisos para resolver este feedback.")
        if actor_empleado_id and int(row.get("responsable_id") or row.get("jefe_directo_id") or 0) == int(actor_empleado_id):
            resolver_feedback(
                feedback_id,
                actor_empleado_id=actor_empleado_id,
                resolucion_descripcion=resolucion,
            )
        elif _can_resolve_as_admin():
            resolver_feedback_admin(
                feedback_id,
                actor_empleado_id=actor_empleado_id,
                resolucion_descripcion=resolucion,
            )
        else:
            raise ValueError("No tiene permisos para resolver este feedback.")
        log_audit(session, "resolver", "feedbacks", feedback_id)
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, msg="Respuesta guardada."))
    except ValueError as exc:
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, error=str(exc)))
    except Exception:
        current_app.logger.exception("feedback_web_resolver_error", extra={"extra": {"feedback_id": feedback_id}})
        return redirect(url_for("feedback_web.registro_detalle", feedback_id=feedback_id, error="No se pudo guardar la respuesta."))


@feedback_web_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo_feedback():
    data = {
        "empleado_id": _parse_int(request.form.get("empleado_id")),
        "cliente_id": _parse_int(request.form.get("cliente_id")),
        "motivo_id": _parse_int(request.form.get("motivo_id")),
        "descripcion": (request.form.get("descripcion") or "").strip(),
    }
    cliente_q = _search_arg("cliente_q", "q", "search", "query")
    errors = []
    if request.method == "POST":
        try:
            evidencia_file = request.files.get("evidencia_file") or request.files.get("evidencia")
            feedback_id = create_feedback(**data, evidencia_file=evidencia_file)
            log_audit(session, "create", "feedbacks", feedback_id)
            return redirect(url_for("feedback_web.registros_listado", msg="Feedback creado."))
        except ValueError as exc:
            errors.append(str(exc))
        except Exception:
            current_app.logger.exception("feedback_web_create_error")
            errors.append("No se pudo crear el feedback.")

    clientes, _ = get_clientes_page(1, 100, search=cliente_q, activo=1)
    return render_template(
        "feedback/feedback_form.html",
        data=data,
        errors=errors,
        empleados=get_empleados(include_inactive=False),
        clientes=clientes,
        motivos=get_motivos(include_inactive=False),
        cliente_q=cliente_q or "",
    )


@feedback_web_bp.route("/motivos")
@role_required("admin", "rrhh")
def motivos_listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    search = _search_arg("q", "search", "query", "cliente_q")
    sector_id = _parse_int(request.args.get("sector_id"))
    activo_raw = (request.args.get("activo") or "").strip().lower()
    activo = None
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    motivos, total = get_motivos_page(page, per_page, search=search, activo=activo, sector_id=sector_id)
    return render_template(
        "feedback/motivos_listado.html",
        motivos=motivos,
        total=total,
        page=page,
        per_page=per_page,
        q=search or "",
        sectores=get_sectores(include_inactive=True),
        sector_id=sector_id,
        activo=activo_raw or "all",
    )


@feedback_web_bp.route("/motivos/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def motivo_nuevo():
    sectores = get_sectores(include_inactive=False)
    if request.method == "POST":
        data = _extract_motivo_form(request.form)
        errors = []
        if not data["nombre"]:
            errors.append("El nombre es obligatorio.")
        if not data["sector_id"]:
            errors.append("El sector responsable es obligatorio.")
        if data["tiempo_resolucion_valor"] <= 0:
            errors.append("El tiempo de resolucion debe ser mayor a cero.")
        if not errors and get_motivo_by_nombre(data["nombre"], data["sector_id"]):
            errors.append("Ya existe un motivo con ese nombre en el sector seleccionado.")
        if errors:
            return render_template(
                "feedback/motivo_form.html",
                mode="new",
                data=data,
                errors=errors,
                sectores=sectores,
            )
        try:
            motivo_id = create_motivo(data)
            log_audit(session, "create", "feedback_motivos", motivo_id)
            return redirect(url_for("feedback_web.motivos_listado", msg="Motivo creado."))
        except Exception as exc:
            current_app.logger.exception("feedback_motivo_create_error")
            return render_template(
                "feedback/motivo_form.html",
                mode="new",
                data=data,
                errors=["No se pudo crear el motivo. Verifique que no exista otro igual en el mismo sector."],
                sectores=sectores,
            )
    return render_template(
        "feedback/motivo_form.html",
        mode="new",
        data={"activo": True, "sla_dias": 1, "tiempo_resolucion_valor": 1, "tiempo_resolucion_unidad": "DIAS", "requiere_observacion": True},
        sectores=sectores,
    )


@feedback_web_bp.route("/motivos/editar/<int:motivo_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def motivo_editar(motivo_id: int):
    motivo = get_motivo_by_id(motivo_id)
    if not motivo:
        return redirect(url_for("feedback_web.motivos_listado", error="Motivo no encontrado."))

    sectores = get_sectores(include_inactive=False)
    if request.method == "POST":
        data = _extract_motivo_form(request.form)
        errors = []
        if not data["nombre"]:
            errors.append("El nombre es obligatorio.")
        if not data["sector_id"]:
            errors.append("El sector responsable es obligatorio.")
        if data["tiempo_resolucion_valor"] <= 0:
            errors.append("El tiempo de resolucion debe ser mayor a cero.")
        if not errors and get_motivo_by_nombre(data["nombre"], data["sector_id"], exclude_id=motivo_id):
            errors.append("Ya existe un motivo con ese nombre en el sector seleccionado.")
        if errors:
            merged = dict(motivo)
            merged.update(data)
            return render_template(
                "feedback/motivo_form.html",
                mode="edit",
                data=merged,
                errors=errors,
                sectores=sectores,
            )
        try:
            update_motivo(motivo_id, data)
            log_audit(session, "update", "feedback_motivos", motivo_id)
            return redirect(url_for("feedback_web.motivos_listado", msg="Motivo actualizado."))
        except Exception as exc:
            current_app.logger.exception("feedback_motivo_update_error")
            merged = dict(motivo)
            merged.update(data)
            return render_template(
                "feedback/motivo_form.html",
                mode="edit",
                data=merged,
                errors=["No se pudo actualizar el motivo. Verifique que no exista otro igual en el mismo sector."],
                sectores=sectores,
            )

    return render_template("feedback/motivo_form.html", mode="edit", data=motivo, sectores=sectores)


@feedback_web_bp.post("/motivos/activar/<int:motivo_id>")
@role_required("admin", "rrhh")
def motivo_activar(motivo_id: int):
    set_motivo_activo(motivo_id, 1)
    log_audit(session, "activate", "feedback_motivos", motivo_id)
    return redirect(url_for("feedback_web.motivos_listado", msg="Motivo activado."))


@feedback_web_bp.post("/motivos/desactivar/<int:motivo_id>")
@role_required("admin", "rrhh")
def motivo_desactivar(motivo_id: int):
    set_motivo_activo(motivo_id, 0)
    log_audit(session, "deactivate", "feedback_motivos", motivo_id)
    return redirect(url_for("feedback_web.motivos_listado", msg="Motivo desactivado."))


@feedback_web_bp.route("/clientes")
@role_required("admin", "rrhh")
def clientes_listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    search = _search_arg("q", "search", "query", "cliente_q")
    activo_raw = (request.args.get("activo") or "").strip().lower()
    activo = None
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    clientes, total = get_clientes_page(page, per_page, search=search, activo=activo)
    total_clientes = count_clientes(include_inactive=True)
    return render_template(
        "feedback/clientes_listado.html",
        clientes=clientes,
        total=total,
        total_clientes=total_clientes,
        page=page,
        per_page=per_page,
        q=search or "",
        activo=activo_raw or "all",
    )


@feedback_web_bp.route("/clientes/importar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def clientes_importar():
    resultado = None
    if request.method == "POST":
        archivo = request.files.get("archivo_csv")
        if not archivo or not str(archivo.filename or "").lower().endswith(".csv"):
            resultado = {"error": "Debe subir un archivo .csv valido."}
        else:
            try:
                resultado = importar_clientes_desde_csv(archivo.stream)
                log_audit(session, "importar_csv", "feedback_clientes", 0)
            except Exception as exc:
                current_app.logger.exception("feedback_clientes_import_error")
                resultado = {"error": f"No se pudo procesar el archivo: {exc}"}

    return render_template("feedback/clientes_importar.html", resultado=resultado)
