from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.configuracion_empresa_repository import get_all, get_by_empresa_id, upsert
from repositories.empresa_repository import get_all as get_empresas
from utils.audit import log_audit

configuracion_bp = Blueprint("configuracion_empresa", __name__, url_prefix="/configuracion-empresa")


def _parse_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@configuracion_bp.route("/")
@role_required("admin")
def listado():
    configs = get_all()
    return render_template("configuracion_empresa/listado.html", configs=configs)


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
        data = {
            "empresa_id": empresa_id,
            "requiere_qr": request.form.get("requiere_qr") == "1",
            "requiere_foto": request.form.get("requiere_foto") == "1",
            "requiere_geo": request.form.get("requiere_geo") == "1",
            "tolerancia_global": _parse_int(request.form.get("tolerancia_global")),
            "cooldown_scan_segundos": _parse_int(request.form.get("cooldown_scan_segundos")),
            "intervalo_minimo_fichadas_minutos": _parse_int(
                request.form.get("intervalo_minimo_fichadas_minutos")
            ),
        }
        upsert(data)
        log_audit(session, "update", "configuracion_empresa", empresa_id)
        return redirect(url_for("configuracion_empresa.listado"))

    return render_template(
        "configuracion_empresa/form.html",
        empresa=empresa,
        data=config
    )
