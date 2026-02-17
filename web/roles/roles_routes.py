from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from web.auth.decorators import role_required
from repositories.rol_repository import get_page, get_by_id, create, update, delete
from utils.audit import log_audit

roles_bp = Blueprint("roles", __name__, url_prefix="/roles")


def _validate(form):
    nombre = (form.get("nombre") or "").strip()
    if not nombre:
        return ["Nombre es requerido."], ""
    return [], nombre


@roles_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    search = request.args.get("q")
    roles, total = get_page(page, per_page, search)
    return render_template(
        "roles/listado.html",
        roles=roles,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@roles_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    if request.method == "POST":
        errors, nombre = _validate(request.form)
        if errors:
            return render_template("roles/form.html", mode="new", data={"nombre": nombre}, errors=errors)
        rol_id = create(nombre)
        log_audit(session, "create", "roles", rol_id)
        return redirect(url_for("roles.listado"))

    return render_template("roles/form.html", mode="new", data={})


@roles_bp.route("/editar/<int:rol_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(rol_id):
    rol = get_by_id(rol_id)
    if not rol:
        abort(404)

    if request.method == "POST":
        errors, nombre = _validate(request.form)
        if errors:
            return render_template("roles/form.html", mode="edit", data={"nombre": nombre}, errors=errors)
        update(rol_id, nombre)
        log_audit(session, "update", "roles", rol_id)
        return redirect(url_for("roles.listado"))

    return render_template("roles/form.html", mode="edit", data=rol)


@roles_bp.route("/eliminar/<int:rol_id>", methods=["POST"])
@role_required("admin")
def eliminar(rol_id):
    delete(rol_id)
    log_audit(session, "delete", "roles", rol_id)
    return redirect(url_for("roles.listado"))
