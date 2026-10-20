from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.configuracion_empresa_repository import get_all, get_by_empresa_id, upsert
from repositories.empresa_repository import get_all as get_empresas
from utils.audit import log_audit
from utils.forms import parse_int as _parse_int
import json
from repositories.configuracion_empresa_repository import save_facial_draft
from repositories.usuarios_app_repository import get_by_id as get_panel_user
from web.facial_draft_forms import parse_draft_form

configuracion_bp = Blueprint("configuracion_empresa", __name__, url_prefix="/configuracion-empresa")


def _parse_non_negative_int(raw, field_label: str, *, default: int | None = None):
    value = _parse_int(raw)
    if value is None:
        return default
    if value < 0:
        raise ValueError(f"{field_label} no puede ser negativo.")
    return value


def _parse_horas_egreso(raw):
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return 8
    try:
        value = round(float(text), 2)
    except ValueError:
        raise ValueError("Horas para el egreso automatico: ingrese un numero.")
    if not 1 <= value <= 16:
        raise ValueError("Horas para el egreso automatico: use un valor entre 1 y 16.")
    return value


@configuracion_bp.route("/")
@role_required("admin")
def listado():
    configs = get_all()
    return render_template(
        "configuracion_empresa/listado.html",
        configs=configs,
        msg=(request.args.get("msg") or "").strip() or None,
        error=(request.args.get("error") or "").strip() or None,
    )


@configuracion_bp.route("/editar/<int:empresa_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(empresa_id):
    empresa = None
    for e in get_empresas(include_inactive=True):
        if e["id"] == empresa_id:
            empresa = e
            break

    if not empresa:
        abort(404)

    config = get_by_empresa_id(empresa_id) or {"empresa_id": empresa_id}

    # The new draft section is restricted by the persisted administrator scope.
    # A null company denotes the existing global administrator.
    panel_user = get_panel_user(session.get("user_id"))
    facial_allowed = bool(panel_user and panel_user.get("activo") and
                          panel_user.get("rol") == "admin" and
                          panel_user.get("empresa_id") in (None, empresa_id))
    facial_ready = facial_allowed and "facial_policy_revision" in config
    if facial_allowed:
        raw_draft = config.get("facial_policy_draft")
        try:
            draft = json.loads(raw_draft) if isinstance(raw_draft, str) else raw_draft
        except (ValueError, TypeError):
            draft = None
        config["facial_draft_mode"] = (draft or {}).get("mode", "disabled") if isinstance(draft, dict) else "disabled"
        config["facial_draft_values"] = draft if isinstance(draft, dict) else {}
    config["facial_allowed"] = facial_allowed
    config["facial_ready"] = facial_ready

    if request.method == "POST" and request.form.get("action") == "save_facial_draft":
        if not facial_allowed:
            abort(403)
        try:
            save_facial_draft(
                empresa_id, parse_draft_form(request.form, config.get("facial_draft_values")),
                revision=int(request.form.get("facial_revision", "")),
                actor_id=int(session["user_id"]),
            )
        except (ValueError, RuntimeError) as exc:
            return render_template("configuracion_empresa/form.html",
                                   empresa=empresa, data=config, error=str(exc)), 400
        return redirect(url_for("configuracion_empresa.editar", empresa_id=empresa_id,
                                facial_saved="1"))

    if request.method == "POST":
        try:
            data = {
                "empresa_id": empresa_id,
                "requiere_qr": request.form.get("requiere_qr") == "1",
                "requiere_foto": request.form.get("requiere_foto") == "1",
                "requiere_geo": request.form.get("requiere_geo") == "1",
                "tolerancia_global": _parse_non_negative_int(request.form.get("tolerancia_global"), "Tolerancia global"),
                "cooldown_scan_segundos": _parse_non_negative_int(
                    request.form.get("cooldown_scan_segundos"),
                    "Cooldown scan QR",
                    default=60,
                ),
                "intervalo_minimo_fichadas_minutos": _parse_non_negative_int(
                    request.form.get("intervalo_minimo_fichadas_minutos"),
                    "Intervalo minimo entre fichadas",
                    default=60,
                ),
                "egreso_automatico_activo": 1 if request.form.get("egreso_automatico_activo") == "1" else 0,
                "egreso_automatico_horas": _parse_horas_egreso(request.form.get("egreso_automatico_horas")),
            }
        except ValueError as exc:
            merged = dict(config)
            merged.update(request.form)
            return render_template(
                "configuracion_empresa/form.html",
                empresa=empresa,
                data=merged,
                error=str(exc),
            )

        try:
            upsert(data)
        except RuntimeError as exc:
            merged = dict(config)
            merged.update(data)
            return render_template(
                "configuracion_empresa/form.html",
                empresa=empresa,
                data=merged,
                error=str(exc),
            )
        log_audit(session, "update", "configuracion_empresa", empresa_id)
        return redirect(url_for("configuracion_empresa.listado", msg="Configuracion guardada."))

    return render_template(
        "configuracion_empresa/form.html",
        empresa=empresa,
        data=config,
        error=None,
    )
