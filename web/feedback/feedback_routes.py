from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from repositories.feedback_cliente_repository import count_all as count_clientes
from repositories.feedback_cliente_repository import get_page as get_clientes_page
from repositories.feedback_motivo_repository import (
    count_all as count_motivos,
    create as create_motivo,
    get_by_id as get_motivo_by_id,
    get_page as get_motivos_page,
    set_activo as set_motivo_activo,
    update as update_motivo,
)
from repositories.sector_repository import get_all as get_sectores
from services.feedback_import_service import importar_clientes_desde_csv
from services.feedback_service import get_feedback_dashboard
from utils.audit import log_audit
from web.auth.decorators import role_required

feedback_web_bp = Blueprint("feedback_web", __name__, url_prefix="/feedback")


def _parse_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _extract_motivo_form(form) -> dict:
    return {
        "nombre": (form.get("nombre") or "").strip(),
        "descripcion": (form.get("descripcion") or "").strip() or None,
        "sla_dias": int(form.get("sla_dias") or 0),
        "activo": str(form.get("activo") or "1").strip() in {"1", "true", "on", "yes", "si"},
    }


@feedback_web_bp.route("/")
@role_required("admin", "rrhh")
def dashboard():
    sector_id = _parse_int(request.args.get("sector_id"))
    empleado_activo_raw = (request.args.get("empleado_activo") or "1").strip().lower()
    empleado_activo = None
    if empleado_activo_raw == "1":
        empleado_activo = 1
    elif empleado_activo_raw == "0":
        empleado_activo = 0
    else:
        empleado_activo_raw = "all"
    datos = get_feedback_dashboard(
        sector_id=sector_id,
        empleado_activo=empleado_activo,
    )
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
        sector_id=sector_id,
        empleado_activo=empleado_activo_raw,
    )


@feedback_web_bp.route("/motivos")
@role_required("admin", "rrhh")
def motivos_listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    search = (request.args.get("q") or "").strip() or None
    activo_raw = (request.args.get("activo") or "").strip().lower()
    activo = None
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    motivos, total = get_motivos_page(page, per_page, search=search, activo=activo)
    return render_template(
        "feedback/motivos_listado.html",
        motivos=motivos,
        total=total,
        page=page,
        per_page=per_page,
        q=search or "",
        activo=activo_raw or "all",
    )


@feedback_web_bp.route("/motivos/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def motivo_nuevo():
    if request.method == "POST":
        data = _extract_motivo_form(request.form)
        errors = []
        if not data["nombre"]:
            errors.append("El nombre es obligatorio.")
        if data["sla_dias"] <= 0:
            errors.append("El SLA debe ser mayor a cero.")
        if errors:
            return render_template(
                "feedback/motivo_form.html",
                mode="new",
                data=data,
                errors=errors,
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
                errors=[str(exc)],
            )
    return render_template("feedback/motivo_form.html", mode="new", data={"activo": True, "sla_dias": 1})


@feedback_web_bp.route("/motivos/editar/<int:motivo_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def motivo_editar(motivo_id: int):
    motivo = get_motivo_by_id(motivo_id)
    if not motivo:
        return redirect(url_for("feedback_web.motivos_listado", error="Motivo no encontrado."))

    if request.method == "POST":
        data = _extract_motivo_form(request.form)
        errors = []
        if not data["nombre"]:
            errors.append("El nombre es obligatorio.")
        if data["sla_dias"] <= 0:
            errors.append("El SLA debe ser mayor a cero.")
        if errors:
            merged = dict(motivo)
            merged.update(data)
            return render_template(
                "feedback/motivo_form.html",
                mode="edit",
                data=merged,
                errors=errors,
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
                errors=[str(exc)],
            )

    return render_template("feedback/motivo_form.html", mode="edit", data=motivo)


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
    search = (request.args.get("q") or "").strip() or None
    activo_raw = (request.args.get("activo") or "").strip().lower()
    activo = None
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    clientes, total = get_clientes_page(page, per_page, search=search, activo=activo)
    return render_template(
        "feedback/clientes_listado.html",
        clientes=clientes,
        total=total,
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
