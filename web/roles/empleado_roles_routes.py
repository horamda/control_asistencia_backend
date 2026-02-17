from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.empleado_repository import get_by_id, get_page_for_roles
from repositories.empresa_repository import get_all as get_empresas
from repositories.rol_repository import get_all as get_roles
from repositories.roles_repository import get_roles_by_empleado, set_roles_for_empleado
from utils.audit import log_audit

empleado_roles_bp = Blueprint("empleado_roles", __name__, url_prefix="/empleado-roles")


@empleado_roles_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empresa_id = request.args.get("empresa_id", type=int)
    search = request.args.get("q")
    empleados, total = get_page_for_roles(page, per_page, empresa_id, search)
    empresas = get_empresas(include_inactive=True)
    return render_template(
        "empleado_roles/listado.html",
        empleados=empleados,
        empresas=empresas,
        empresa_id=empresa_id,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@empleado_roles_bp.route("/<int:empleado_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(empleado_id):
    emp = get_by_id(empleado_id)
    if not emp:
        abort(404)

    roles = get_roles()
    current_roles = get_roles_by_empleado(empleado_id)
    current_ids = {r["id"] for r in current_roles}

    if request.method == "POST":
        role_ids = request.form.getlist("roles")
        ids = []
        for rid in role_ids:
            if rid.isdigit():
                ids.append(int(rid))

        set_roles_for_empleado(empleado_id, ids)
        log_audit(session, "assign", "empleado_roles", empleado_id)
        return redirect(url_for("empleado_roles.listado"))

    return render_template(
        "empleado_roles/form.html",
        empleado=emp,
        roles=roles,
        current_ids=current_ids
    )
