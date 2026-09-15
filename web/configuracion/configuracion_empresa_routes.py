from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.configuracion_empresa_repository import get_all, get_by_empresa_id, upsert
from repositories.empresa_repository import get_all as get_empresas
from utils.audit import log_audit
from utils.forms import parse_int as _parse_int

configuracion_bp = Blueprint("configuracion_empresa", __name__, url_prefix="/configuracion-empresa")


def _parse_non_negative_int(raw, field_label: str, *, default: int | None = None):
    value = _parse_int(raw)
    if value is None:
        return default
    if value < 0:
        raise ValueError(f"{field_label} no puede ser negativo.")
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
