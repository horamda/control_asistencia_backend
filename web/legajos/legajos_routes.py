import datetime
from urllib.parse import urlparse

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from repositories.empleado_repository import get_all as get_empleados
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.empresa_repository import get_all as get_empresas
from repositories.legajo_adjunto_repository import (
    create_adjunto,
    get_adjunto_by_id,
    get_adjuntos_by_evento,
    mark_deleted,
)
from repositories.legajo_evento_repository import (
    anular_evento,
    create_evento,
    get_evento_by_id,
    get_eventos_page,
    get_eventos_by_empleado,
    get_tipo_evento_by_id,
    get_tipos_evento,
    update_evento,
)
from services.legajo_attachment_service import save_legajo_attachment_local
from utils.audit import log_audit
from web.auth.decorators import role_required

legajos_bp = Blueprint("legajos", __name__, url_prefix="/legajos")


def _parse_int(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return None


def _parse_date(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    return datetime.date.fromisoformat(value).isoformat()


def _safe_next_url(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return None
    if not raw.startswith("/"):
        return None
    return raw


def _extract_evento_form(form):
    return {
        "tipo_id": _parse_int(form.get("tipo_id")),
        "fecha_evento": (form.get("fecha_evento") or "").strip(),
        "fecha_desde": (form.get("fecha_desde") or "").strip(),
        "fecha_hasta": (form.get("fecha_hasta") or "").strip(),
        "titulo": (form.get("titulo") or "").strip(),
        "descripcion": (form.get("descripcion") or "").strip(),
        "severidad": (form.get("severidad") or "").strip() or None,
        "justificacion_id": _parse_int(form.get("justificacion_id")),
    }


def _date_to_input_value(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _evento_to_form_data(evento: dict):
    return {
        "tipo_id": evento.get("tipo_id"),
        "fecha_evento": _date_to_input_value(evento.get("fecha_evento")),
        "fecha_desde": _date_to_input_value(evento.get("fecha_desde")),
        "fecha_hasta": _date_to_input_value(evento.get("fecha_hasta")),
        "titulo": evento.get("titulo") or "",
        "descripcion": evento.get("descripcion") or "",
        "severidad": evento.get("severidad") or "",
        "justificacion_id": evento.get("justificacion_id"),
    }


def _validate_evento_data(data: dict, tipo: dict | None):
    errors = []
    if not data.get("tipo_id"):
        errors.append("Tipo de evento es requerido.")
    if not tipo or not tipo.get("activo"):
        errors.append("Tipo de evento invalido.")

    try:
        data["fecha_evento"] = _parse_date(data.get("fecha_evento"))
    except ValueError:
        errors.append("Fecha de evento invalida.")

    try:
        data["fecha_desde"] = _parse_date(data.get("fecha_desde"))
    except ValueError:
        errors.append("Fecha desde invalida.")

    try:
        data["fecha_hasta"] = _parse_date(data.get("fecha_hasta"))
    except ValueError:
        errors.append("Fecha hasta invalida.")

    if not data.get("descripcion"):
        errors.append("Descripcion es requerida.")

    if data.get("severidad") and data["severidad"] not in {"leve", "media", "grave"}:
        errors.append("Severidad invalida.")

    if data.get("fecha_desde") and data.get("fecha_hasta"):
        if data["fecha_hasta"] < data["fecha_desde"]:
            errors.append("Fecha hasta debe ser mayor o igual a fecha desde.")

    if tipo and tipo.get("requiere_rango_fechas"):
        if not data.get("fecha_desde") or not data.get("fecha_hasta"):
            errors.append("Este tipo requiere fecha desde y fecha hasta.")

    return errors


def _build_evento_payload(data: dict, *, empresa_id: int, empleado_id: int, actor_id: int | None):
    return {
        "empresa_id": empresa_id,
        "empleado_id": empleado_id,
        "tipo_id": data.get("tipo_id"),
        "fecha_evento": data.get("fecha_evento"),
        "fecha_desde": data.get("fecha_desde"),
        "fecha_hasta": data.get("fecha_hasta"),
        "titulo": data.get("titulo") or None,
        "descripcion": data.get("descripcion"),
        "severidad": data.get("severidad"),
        "justificacion_id": data.get("justificacion_id"),
        "created_by_usuario_id": actor_id,
        "updated_by_usuario_id": actor_id,
    }


def _load_empleado_context(emp_id: int):
    empleado = get_empleado_by_id(emp_id)
    if not empleado:
        abort(404)
    eventos = get_eventos_by_empleado(emp_id, include_anulados=True)
    tipos = get_tipos_evento(include_inactive=False)
    adjuntos_by_evento = {}
    for evento in eventos:
        evento_id = int(evento["id"])
        adjuntos_by_evento[evento_id] = get_adjuntos_by_evento(evento_id, include_deleted=False)
    return empleado, eventos, tipos, adjuntos_by_evento


@legajos_bp.route("/")
@role_required("admin", "rrhh", "supervisor")
def listado_empleados():
    empleados = get_empleados(include_inactive=True)
    return render_template("legajos/listado.html", empleados=empleados)


@legajos_bp.route("/eventos/")
@role_required("admin", "rrhh", "supervisor")
def listado_eventos():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    if per_page not in {10, 20, 50, 100}:
        per_page = 20

    search = str(request.args.get("q") or "").strip() or None
    empresa_id = request.args.get("empresa_id", type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    tipo_id = request.args.get("tipo_id", type=int)

    estado_raw = str(request.args.get("estado") or "all").strip().lower()
    if estado_raw not in {"all", "vigente", "anulado"}:
        estado_raw = "all"
    estado = None if estado_raw == "all" else estado_raw

    eventos, total = get_eventos_page(
        page=page,
        per_page=per_page,
        search=search,
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        tipo_id=tipo_id,
        estado=estado,
    )
    empresas = get_empresas(include_inactive=True)
    empleados = get_empleados(include_inactive=True)
    tipos = get_tipos_evento(include_inactive=True)

    return render_template(
        "legajos/eventos_listado.html",
        eventos=eventos,
        total=total,
        page=page,
        per_page=per_page,
        q=search,
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        tipo_id=tipo_id,
        estado=estado_raw,
        empresas=empresas,
        empleados=empleados,
        tipos=tipos,
    )


@legajos_bp.route("/empleado/<int:emp_id>")
@role_required("admin", "rrhh", "supervisor")
def empleado(emp_id):
    empleado_data, eventos, tipos, adjuntos_by_evento = _load_empleado_context(emp_id)
    return render_template(
        "legajos/empleado.html",
        empleado=empleado_data,
        eventos=eventos,
        tipos=tipos,
        adjuntos_by_evento=adjuntos_by_evento,
        errors=[],
        form_data={},
    )


@legajos_bp.route("/empleado/<int:emp_id>/eventos", methods=["POST"])
@role_required("admin", "rrhh")
def crear_evento(emp_id):
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)

    data = _extract_evento_form(request.form)
    tipo = get_tipo_evento_by_id(data.get("tipo_id")) if data.get("tipo_id") else None
    errors = _validate_evento_data(data, tipo)

    if errors:
        _, eventos, tipos, adjuntos_by_evento = _load_empleado_context(emp_id)
        return render_template(
            "legajos/empleado.html",
            empleado=empleado_data,
            eventos=eventos,
            tipos=tipos,
            adjuntos_by_evento=adjuntos_by_evento,
            errors=errors,
            form_data=data,
        )

    actor_id = session.get("user_id")
    payload = _build_evento_payload(
        data,
        empresa_id=int(empleado_data["empresa_id"]),
        empleado_id=int(emp_id),
        actor_id=actor_id,
    )
    payload["estado"] = "vigente"
    evento_id = create_evento(payload)
    log_audit(session, "create", "legajo_eventos", evento_id)

    archivos = request.files.getlist("adjuntos")
    for file_storage in archivos:
        if not file_storage or not str(file_storage.filename or "").strip():
            continue
        saved = save_legajo_attachment_local(
            file_storage,
            empresa_id=int(empleado_data["empresa_id"]),
            empleado_id=int(emp_id),
            evento_id=int(evento_id),
        )
        adjunto_id = create_adjunto(
            {
                "evento_id": evento_id,
                "empresa_id": int(empleado_data["empresa_id"]),
                "empleado_id": int(emp_id),
                "nombre_original": saved["nombre_original"],
                "mime_type": saved["mime_type"],
                "extension": saved["extension"],
                "tamano_bytes": saved["tamano_bytes"],
                "sha256": saved["sha256"],
                "storage_backend": saved["storage_backend"],
                "storage_ruta": saved["storage_ruta"],
                "storage_data": saved.get("storage_data"),
                "created_by_usuario_id": actor_id,
            }
        )
        log_audit(session, "create", "legajo_evento_adjuntos", adjunto_id)

    return redirect(url_for("legajos.empleado", emp_id=emp_id))


@legajos_bp.route("/empleado/<int:emp_id>/eventos/<int:evento_id>/editar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar_evento(emp_id, evento_id):
    next_url = _safe_next_url(request.values.get("next"))
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)
    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)
    if str(evento.get("estado") or "").lower() == "anulado":
        abort(400, description="No se puede editar un evento anulado.")

    tipos = get_tipos_evento(include_inactive=False)
    errors = []
    form_data = _evento_to_form_data(evento)

    if request.method == "POST":
        form_data = _extract_evento_form(request.form)
        tipo = get_tipo_evento_by_id(form_data.get("tipo_id")) if form_data.get("tipo_id") else None
        errors = _validate_evento_data(form_data, tipo)
        if not errors:
            actor_id = session.get("user_id")
            payload = _build_evento_payload(
                form_data,
                empresa_id=int(empleado_data["empresa_id"]),
                empleado_id=int(emp_id),
                actor_id=actor_id,
            )
            update_evento(evento_id, payload)
            log_audit(session, "update", "legajo_eventos", evento_id)
            return redirect(next_url or url_for("legajos.empleado", emp_id=emp_id))

    return render_template(
        "legajos/evento_form.html",
        mode="edit",
        empleado=empleado_data,
        evento=evento,
        tipos=tipos,
        errors=errors,
        form_data=form_data,
        next_url=next_url,
    )


@legajos_bp.route("/empleado/<int:emp_id>/eventos/<int:evento_id>/anular", methods=["POST"])
@role_required("admin", "rrhh")
def anular_evento_route(emp_id, evento_id):
    next_url = _safe_next_url(request.values.get("next"))
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)
    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)

    motivo = (request.form.get("motivo_anulacion") or "").strip() or None
    actor_id = session.get("user_id")
    anular_evento(evento_id, actor_id, motivo)
    log_audit(session, "anular", "legajo_eventos", evento_id)
    return redirect(next_url or url_for("legajos.empleado", emp_id=emp_id))


@legajos_bp.route("/empleado/<int:emp_id>/eventos/<int:evento_id>/adjuntos", methods=["POST"])
@role_required("admin", "rrhh")
def agregar_adjuntos(emp_id, evento_id):
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)
    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)
    if str(evento.get("estado") or "").lower() == "anulado":
        abort(400, description="No se pueden adjuntar archivos a un evento anulado.")

    actor_id = session.get("user_id")
    archivos = request.files.getlist("adjuntos")
    for file_storage in archivos:
        if not file_storage or not str(file_storage.filename or "").strip():
            continue
        saved = save_legajo_attachment_local(
            file_storage,
            empresa_id=int(empleado_data["empresa_id"]),
            empleado_id=int(emp_id),
            evento_id=int(evento_id),
        )
        adjunto_id = create_adjunto(
            {
                "evento_id": evento_id,
                "empresa_id": int(empleado_data["empresa_id"]),
                "empleado_id": int(emp_id),
                "nombre_original": saved["nombre_original"],
                "mime_type": saved["mime_type"],
                "extension": saved["extension"],
                "tamano_bytes": saved["tamano_bytes"],
                "sha256": saved["sha256"],
                "storage_backend": saved["storage_backend"],
                "storage_ruta": saved["storage_ruta"],
                "storage_data": saved.get("storage_data"),
                "created_by_usuario_id": actor_id,
            }
        )
        log_audit(session, "create", "legajo_evento_adjuntos", adjunto_id)

    return redirect(url_for("legajos.empleado", emp_id=emp_id))


@legajos_bp.route(
    "/empleado/<int:emp_id>/eventos/<int:evento_id>/adjuntos/<int:adjunto_id>/eliminar",
    methods=["POST"],
)
@role_required("admin", "rrhh")
def eliminar_adjunto(emp_id, evento_id, adjunto_id):
    empleado_data = get_empleado_by_id(emp_id)
    if not empleado_data:
        abort(404)

    evento = get_evento_by_id(evento_id)
    if not evento or int(evento["empleado_id"]) != int(emp_id):
        abort(404)
    if str(evento.get("estado") or "").lower() == "anulado":
        abort(400, description="No se pueden eliminar adjuntos de un evento anulado.")

    adjunto = get_adjunto_by_id(adjunto_id)
    if not adjunto or int(adjunto["evento_id"]) != int(evento_id):
        abort(404)
    if str(adjunto.get("estado") or "").lower() != "activo":
        return redirect(url_for("legajos.empleado", emp_id=emp_id))

    actor_id = session.get("user_id")
    mark_deleted(adjunto_id, actor_id)
    log_audit(session, "delete", "legajo_evento_adjuntos", adjunto_id)
    return redirect(url_for("legajos.empleado", emp_id=emp_id))
