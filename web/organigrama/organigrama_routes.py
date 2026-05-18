from flask import Blueprint, render_template, request, session

from repositories.empresa_repository import get_all as get_empresas
from repositories.organigrama_repository import get_organigrama
from web.auth.decorators import role_required

organigrama_bp = Blueprint("organigrama", __name__, url_prefix="/organigrama")


def _parse_activo(value: str | None):
    raw = str(value or "1").strip().lower()
    if raw == "0":
        return 0, "0"
    if raw == "all":
        return None, "all"
    return 1, "1"


@organigrama_bp.route("/")
@role_required("admin", "rrhh", "supervisor")
def listado():
    empresa_id = request.args.get("empresa_id", type=int)
    activo, activo_raw = _parse_activo(request.args.get("activo"))
    empresas = get_empresas(include_inactive=False)
    organigramas = get_organigrama(empresa_id=empresa_id, activo=activo)
    can_manage_sectors = str(session.get("rol") or "").lower() == "admin"
    return render_template(
        "organigrama/listado.html",
        organigramas=organigramas,
        empresas=empresas,
        empresa_id=empresa_id,
        activo=activo_raw,
        can_manage_sectors=can_manage_sectors,
    )
