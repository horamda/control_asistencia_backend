import json

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from repositories.empresa_repository import get_all as get_empresas
from repositories.horario_repository import get_by_id, set_activo
from services.horario_service import (
    create_horario_estructurado,
    delete_horario_estructurado,
    get_horario_estructurado,
    get_horarios_resumen,
    update_horario_estructurado,
)
from utils.audit import log_audit
from web.auth.decorators import role_required

horarios_bp = Blueprint("horarios", __name__, url_prefix="/horarios")


def _parse_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_dias_payload(raw_payload: str):
    raw_payload = (raw_payload or "").strip()
    if not raw_payload:
        return []
    parsed = json.loads(raw_payload)
    if not isinstance(parsed, list):
        raise ValueError("dias_payload debe ser una lista JSON.")
    return parsed


def _extract_form_data(form):
    dias_payload_raw = (form.get("dias_payload") or "").strip()
    return {
        "empresa_id": _parse_int(form.get("empresa_id")),
        "nombre": (form.get("nombre") or "").strip(),
        "tolerancia_min": _parse_int(form.get("tolerancia_min")),
        "descripcion": (form.get("descripcion") or "").strip(),
        "activo": form.get("activo") == "1",
        "dias": _parse_dias_payload(dias_payload_raw),
        "dias_payload_raw": dias_payload_raw,
    }


@horarios_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    horarios = get_horarios_resumen(include_inactive=True)
    error = (request.args.get("error") or "").strip()
    return render_template("horarios/listado.html", horarios=horarios, error=error)


@horarios_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    empresas = get_empresas()
    if request.method == "POST":
        try:
            data = _extract_form_data(request.form)
            payload = {
                "empresa_id": data["empresa_id"],
                "nombre": data["nombre"],
                "tolerancia_min": data["tolerancia_min"],
                "descripcion": data["descripcion"],
                "activo": data["activo"],
                "dias": data["dias"],
            }
            horario_id = create_horario_estructurado(payload)
            log_audit(session, "create", "horarios", horario_id)
            return redirect(url_for("horarios.listado"))
        except (ValueError, json.JSONDecodeError) as exc:
            return render_template(
                "horarios/form.html",
                mode="new",
                data={
                    "empresa_id": request.form.get("empresa_id"),
                    "nombre": request.form.get("nombre"),
                    "tolerancia_min": request.form.get("tolerancia_min"),
                    "descripcion": request.form.get("descripcion"),
                    "activo": request.form.get("activo") == "1",
                    "dias_payload": request.form.get("dias_payload") or "[]",
                },
                errors=[str(exc)],
                empresas=empresas,
            )

    return render_template(
        "horarios/form.html",
        mode="new",
        data={"activo": True, "dias_payload": "[]"},
        empresas=empresas,
    )


@horarios_bp.route("/editar/<int:horario_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(horario_id):
    horario = get_horario_estructurado(horario_id)
    if not horario:
        return redirect(url_for("horarios.listado", error="Horario no encontrado."))

    empresas = get_empresas(include_inactive=True)
    if request.method == "POST":
        try:
            data = _extract_form_data(request.form)
            payload = {
                "empresa_id": data["empresa_id"],
                "nombre": data["nombre"],
                "tolerancia_min": data["tolerancia_min"],
                "descripcion": data["descripcion"],
                "activo": data["activo"],
                "dias": data["dias"],
            }
            update_horario_estructurado(horario_id, payload)
            log_audit(session, "update", "horarios", horario_id)
            return redirect(url_for("horarios.listado"))
        except (ValueError, json.JSONDecodeError) as exc:
            return render_template(
                "horarios/form.html",
                mode="edit",
                data={
                    "id": horario_id,
                    "empresa_id": request.form.get("empresa_id"),
                    "nombre": request.form.get("nombre"),
                    "tolerancia_min": request.form.get("tolerancia_min"),
                    "descripcion": request.form.get("descripcion"),
                    "activo": request.form.get("activo") == "1",
                    "dias_payload": request.form.get("dias_payload") or "[]",
                },
                errors=[str(exc)],
                empresas=empresas,
            )

    return render_template(
        "horarios/form.html",
        mode="edit",
        data={
            "id": horario["id"],
            "empresa_id": horario["empresa_id"],
            "nombre": horario["nombre"],
            "tolerancia_min": horario["tolerancia_min"],
            "descripcion": horario["descripcion"],
            "activo": bool(horario["activo"]),
            "dias_payload": json.dumps(horario["dias"], ensure_ascii=False),
        },
        empresas=empresas,
    )


@horarios_bp.route("/activar/<int:horario_id>")
@role_required("admin", "rrhh")
def activar(horario_id):
    row = get_by_id(horario_id)
    if not row:
        return redirect(url_for("horarios.listado", error="Horario no encontrado."))
    set_activo(horario_id, 1)
    log_audit(session, "activate", "horarios", horario_id)
    return redirect(url_for("horarios.listado"))


@horarios_bp.route("/desactivar/<int:horario_id>")
@role_required("admin", "rrhh")
def desactivar(horario_id):
    row = get_by_id(horario_id)
    if not row:
        return redirect(url_for("horarios.listado", error="Horario no encontrado."))
    set_activo(horario_id, 0)
    log_audit(session, "deactivate", "horarios", horario_id)
    return redirect(url_for("horarios.listado"))


@horarios_bp.route("/eliminar/<int:horario_id>", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar(horario_id):
    try:
        delete_horario_estructurado(horario_id)
        log_audit(session, "delete", "horarios", horario_id)
        return redirect(url_for("horarios.listado"))
    except ValueError as exc:
        return redirect(url_for("horarios.listado", error=str(exc)))
    except Exception:
        return redirect(url_for("horarios.listado", error="No se pudo eliminar el horario por una relacion vigente."))


@horarios_bp.route("/api", methods=["GET"])
@role_required("admin", "rrhh")
def api_list():
    return jsonify(get_horarios_resumen(include_inactive=True))


@horarios_bp.route("/api/<int:horario_id>", methods=["GET"])
@role_required("admin", "rrhh")
def api_get(horario_id):
    horario = get_horario_estructurado(horario_id)
    if not horario:
        return jsonify({"error": "Horario no encontrado"}), 404
    return jsonify(horario)


@horarios_bp.route("/api", methods=["POST"])
@role_required("admin", "rrhh")
def api_create():
    payload = request.get_json(silent=True) or {}
    try:
        horario_id = create_horario_estructurado(payload)
        log_audit(session, "create", "horarios", horario_id)
        return jsonify({"id": horario_id}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@horarios_bp.route("/api/<int:horario_id>", methods=["PUT"])
@role_required("admin", "rrhh")
def api_update(horario_id):
    payload = request.get_json(silent=True) or {}
    try:
        update_horario_estructurado(horario_id, payload)
        log_audit(session, "update", "horarios", horario_id)
        return jsonify({"ok": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@horarios_bp.route("/api/<int:horario_id>", methods=["DELETE"])
@role_required("admin", "rrhh")
def api_delete(horario_id):
    try:
        delete_horario_estructurado(horario_id)
        log_audit(session, "delete", "horarios", horario_id)
        return jsonify({"ok": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "No se pudo eliminar el horario por una relacion vigente."}), 400

