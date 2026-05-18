from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.app_version_repository import (
    get_all,
    get_by_id,
    create,
    update,
    delete,
)
from utils.audit import log_audit

app_version_bp = Blueprint("app_version", __name__, url_prefix="/app-version")

_PLATFORMS = ("android", "ios", "all")


def _extract(form) -> dict:
    return {
        "platform": (form.get("platform") or "android").strip().lower(),
        "version_minima": (form.get("version_minima") or "1.0.0").strip(),
        "version_recomendada": (form.get("version_recomendada") or "1.0.0").strip(),
        "url_descarga": (form.get("url_descarga") or "").strip() or None,
        "mensaje": (form.get("mensaje") or "").strip() or None,
        "activo": form.get("activo") == "1",
    }


def _validate(data: dict) -> list[str]:
    errors = []
    if data.get("platform") not in _PLATFORMS:
        errors.append("Plataforma inválida. Use android, ios o all.")

    for field in ("version_minima", "version_recomendada"):
        val = data.get(field) or ""
        parts = val.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            errors.append(f"{field} debe tener formato X.Y.Z (ej: 1.2.0).")

    return errors


@app_version_bp.route("/")
@role_required("admin")
def listado():
    configs = get_all()
    return render_template("app_version/listado.html", configs=configs, platforms=_PLATFORMS)


@app_version_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    data = {}
    errors = []
    if request.method == "POST":
        data = _extract(request.form)
        errors = _validate(data)
        if not errors:
            cfg_id = create(data)
            log_audit(session, "create", "app_version_config", cfg_id)
            return redirect(url_for("app_version.listado"))
    return render_template(
        "app_version/form.html",
        mode="new",
        data=data,
        errors=errors,
        platforms=_PLATFORMS,
    )


@app_version_bp.route("/editar/<int:config_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(config_id):
    cfg = get_by_id(config_id)
    if not cfg:
        abort(404)
    errors = []
    if request.method == "POST":
        data = _extract(request.form)
        errors = _validate(data)
        if not errors:
            update(config_id, data)
            log_audit(session, "update", "app_version_config", config_id)
            return redirect(url_for("app_version.listado"))
        cfg = dict(cfg)
        cfg.update(data)
    return render_template(
        "app_version/form.html",
        mode="edit",
        data=cfg,
        errors=errors,
        platforms=_PLATFORMS,
    )


@app_version_bp.route("/eliminar/<int:config_id>", methods=["POST"])
@role_required("admin")
def eliminar(config_id):
    cfg = get_by_id(config_id)
    if not cfg:
        abort(404)
    delete(config_id)
    log_audit(session, "delete", "app_version_config", config_id)
    return redirect(url_for("app_version.listado"))
