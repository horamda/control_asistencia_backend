from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from werkzeug.security import generate_password_hash
from web.auth.decorators import role_required
from repositories.usuarios_app_repository import (
    get_page,
    get_by_id,
    create,
    update,
    update_password,
    set_activo,
    exists_unique
)
from repositories.web_permission_repository import get_user_permissions, set_user_permissions
from repositories.empresa_repository import get_all as get_empresas
from repositories.empleado_repository import get_all as get_empleados
from services.web_permissions_service import (
    PERMISSION_ACTIONS,
    WEB_MODULES,
    default_permission_payload_for_role,
)
from utils.audit import log_audit
from utils.validators import UsuarioValidator

usuarios_bp = Blueprint("usuarios", __name__, url_prefix="/usuarios")


def _validate(form, require_password: bool, user_id: int | None = None):
    validator = UsuarioValidator()
    return validator.validate(form, require_password=require_password, user_id=user_id, exists_unique=exists_unique)


def _empleados_para_vincular():
    return get_empleados(include_inactive=False)


def _permissions_from_form(form, rol: str | None) -> dict[str, dict[str, bool]]:
    defaults = default_permission_payload_for_role(rol)
    permissions = {}
    for module in WEB_MODULES:
        code = module["code"]
        permissions[code] = {}
        for action in PERMISSION_ACTIONS:
            field = f"perm_{code}_{action}"
            permissions[code][action] = field in form
        # Si puede realizar cualquier accion operativa, tambien puede ver el modulo.
        if any(permissions[code].get(action) for action in PERMISSION_ACTIONS if action != "ver"):
            permissions[code]["ver"] = True
    if not any(any(actions.values()) for actions in permissions.values()):
        return defaults
    return permissions


def _permissions_for_form(user_id: int | None, rol: str | None):
    if user_id:
        current = get_user_permissions(user_id)
        if current:
            return current
    return default_permission_payload_for_role(rol)


@usuarios_bp.route("/")
@role_required("admin")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empresa_id = request.args.get("empresa_id", type=int)
    activo = request.args.get("activo", default=None, type=int)
    search = request.args.get("q")
    usuarios, total = get_page(page, per_page, empresa_id, activo, search)
    empresas = get_empresas(include_inactive=True)
    return render_template(
        "usuarios/listado.html",
        usuarios=usuarios,
        empresas=empresas,
        empresa_id=empresa_id,
        activo=activo,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@usuarios_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empresas = get_empresas(include_inactive=True)
    empleados = _empleados_para_vincular()
    if request.method == "POST":
        errors, usuario, empresa_id, rol, empleado_id = _validate(request.form, require_password=True, user_id=None)
        activo = request.form.get("activo") == "1"
        if errors:
            return render_template(
                "usuarios/form.html",
                mode="new",
                data={"usuario": usuario, "empresa_id": empresa_id, "rol": rol, "activo": activo, "empleado_id": empleado_id},
                errors=errors,
                password_required=True,
                empresas=empresas,
                empleados=empleados,
                modules=WEB_MODULES,
                actions=PERMISSION_ACTIONS,
                permissions=_permissions_from_form(request.form, rol),
            )

        password = (request.form.get("password") or "").strip()
        permissions = _permissions_from_form(request.form, rol)
        new_id = create({
            "empresa_id": empresa_id,
            "empleado_id": empleado_id,
            "usuario": usuario,
            "password_hash": generate_password_hash(password),
            "rol": rol,
            "activo": activo
        })
        set_user_permissions(new_id, permissions)
        log_audit(session, "create", "usuarios", new_id)
        return redirect(url_for("usuarios.listado"))

    return render_template(
        "usuarios/form.html",
        mode="new",
        data={"activo": True},
        password_required=True,
        empresas=empresas,
        empleados=empleados,
        modules=WEB_MODULES,
        actions=PERMISSION_ACTIONS,
        permissions=default_permission_payload_for_role("supervisor"),
    )


@usuarios_bp.route("/editar/<int:user_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(user_id):
    user = get_by_id(user_id)
    if not user:
        abort(404)

    empresas = get_empresas(include_inactive=True)
    empleados = _empleados_para_vincular()
    if request.method == "POST":
        errors, usuario, empresa_id, rol, empleado_id = _validate(request.form, require_password=False, user_id=user_id)
        activo = request.form.get("activo") == "1"
        if errors:
            return render_template(
                "usuarios/form.html",
                mode="edit",
                data={"usuario": usuario, "empresa_id": empresa_id, "rol": rol, "activo": activo, "empleado_id": empleado_id},
                errors=errors,
                password_required=False,
                empresas=empresas,
                empleados=empleados,
                modules=WEB_MODULES,
                actions=PERMISSION_ACTIONS,
                permissions=_permissions_from_form(request.form, rol),
            )

        update(user_id, {
            "empresa_id": empresa_id,
            "empleado_id": empleado_id,
            "usuario": usuario,
            "rol": rol,
            "activo": activo
        })
        set_user_permissions(user_id, _permissions_from_form(request.form, rol))
        log_audit(session, "update", "usuarios", user_id)

        password = (request.form.get("password") or "").strip()
        if password:
            update_password(user_id, generate_password_hash(password))
            log_audit(session, "update_password", "usuarios", user_id)

        return redirect(url_for("usuarios.listado"))

    return render_template(
        "usuarios/form.html",
        mode="edit",
        data=user,
        password_required=False,
        empresas=empresas,
        empleados=empleados,
        modules=WEB_MODULES,
        actions=PERMISSION_ACTIONS,
        permissions=_permissions_for_form(user_id, user.get("rol")),
    )


@usuarios_bp.route("/activar/<int:user_id>")
@role_required("admin")
def activar(user_id):
    set_activo(user_id, 1)
    log_audit(session, "activate", "usuarios", user_id)
    return redirect(url_for("usuarios.listado"))


@usuarios_bp.route("/desactivar/<int:user_id>")
@role_required("admin")
def desactivar(user_id):
    set_activo(user_id, 0)
    log_audit(session, "deactivate", "usuarios", user_id)
    return redirect(url_for("usuarios.listado"))
