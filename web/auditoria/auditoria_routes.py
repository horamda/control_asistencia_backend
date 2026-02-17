from flask import Blueprint, render_template, request
from web.auth.decorators import role_required
from repositories.auditoria_repository import get_page

auditoria_bp = Blueprint("auditoria", __name__, url_prefix="/auditoria")


@auditoria_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    registros, total = get_page(page, per_page)
    return render_template(
        "auditoria/listado.html",
        registros=registros,
        page=page,
        per_page=per_page,
        total=total
    )
