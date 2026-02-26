from flask import Blueprint, render_template, redirect, url_for, request, abort, session
from werkzeug.security import generate_password_hash
from web.auth.decorators import role_required
from repositories.empleado_repository import (
    get_page,
    get_by_id,
    create,
    update,
    update_password,
    set_activo,
    exists_unique
)
from repositories.empresa_repository import get_all as get_empresas
from repositories.sucursal_repository import get_all as get_sucursales
from repositories.sector_repository import get_all as get_sectores
from repositories.puesto_repository import get_all as get_puestos
from repositories.localidad_repository import get_all as get_localidades, exists_codigo
from utils.audit import log_audit
from utils.validators import EmpleadoValidator

empleados_bp = Blueprint("empleados", __name__, url_prefix="/empleados")


def _parse_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _extract_form_data(form):
    return {
        "empresa_id": _parse_int(form.get("empresa_id")),
        "sucursal_id": _parse_int(form.get("sucursal_id")),
        "sector_id": _parse_int(form.get("sector_id")),
        "puesto_id": _parse_int(form.get("puesto_id")),
        "codigo_postal": (form.get("codigo_postal") or "").strip(),
        "legajo": (form.get("legajo") or "").strip(),
        "dni": (form.get("dni") or "").strip(),
        "nombre": (form.get("nombre") or "").strip(),
        "apellido": (form.get("apellido") or "").strip(),
        "fecha_nacimiento": (form.get("fecha_nacimiento") or "").strip(),
        "sexo": (form.get("sexo") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "telefono": (form.get("telefono") or "").strip(),
        "direccion": (form.get("direccion") or "").strip(),
        "puesto": (form.get("puesto") or "").strip(),
        "sector": (form.get("sector") or "").strip(),
        "fecha_ingreso": (form.get("fecha_ingreso") or "").strip(),
        "estado": (form.get("estado") or "activo").strip() or "activo",
        "foto": (form.get("foto") or "").strip()
    }


@empleados_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    search = request.args.get("q")
    empresa_id = request.args.get("empresa_id", type=int)
    empleados, total = get_page(page, per_page, include_inactive=True, search=search, empresa_id=empresa_id)
    empresas = get_empresas(include_inactive=True)
    return render_template(
        "empleados/listado.html",
        empleados=empleados,
        empresas=empresas,
        empresa_id=empresa_id,
        q=search,
        page=page,
        per_page=per_page,
        total=total
    )


@empleados_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    empresas = get_empresas()
    sucursales = get_sucursales(include_inactive=True)
    sectores = get_sectores(include_inactive=True)
    puestos = get_puestos(include_inactive=True)
    localidades = get_localidades()
    if request.method == "POST":
        validator = EmpleadoValidator()
        errors = validator.validate(request.form, require_password=True, emp_id=None, exists_unique=exists_unique, exists_codigo=exists_codigo)
        data = _extract_form_data(request.form)

        if errors:
            return render_template(
                "empleados/form.html",
                mode="new",
                data=data,
                errors=errors,
                password_required=True,
                empresas=empresas,
                sucursales=sucursales,
                sectores=sectores,
                puestos=puestos,
                localidades=localidades
            )

        password = (request.form.get("password") or "").strip()
        data["password_hash"] = generate_password_hash(password)

        emp_id = create(data)
        log_audit(session, "create", "empleados", emp_id)
        return redirect(url_for("empleados.listado"))

    return render_template(
        "empleados/form.html",
        mode="new",
        data={},
        password_required=True,
        empresas=empresas,
        sucursales=sucursales,
        sectores=sectores,
        puestos=puestos,
        localidades=localidades
    )


@empleados_bp.route("/editar/<int:emp_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(emp_id):
    emp = get_by_id(emp_id)
    if not emp:
        abort(404)

    empresas = get_empresas(include_inactive=True)
    sucursales = get_sucursales(include_inactive=True)
    sectores = get_sectores(include_inactive=True)
    puestos = get_puestos(include_inactive=True)
    localidades = get_localidades()

    if request.method == "POST":
        validator = EmpleadoValidator()
        errors = validator.validate(request.form, require_password=False, emp_id=emp_id, exists_unique=exists_unique, exists_codigo=exists_codigo)
        data = _extract_form_data(request.form)

        if errors:
            merged = dict(emp)
            merged.update(data)
            return render_template(
                "empleados/form.html",
                mode="edit",
                data=merged,
                errors=errors,
                password_required=False,
                empresas=empresas,
                sucursales=sucursales,
                sectores=sectores,
                puestos=puestos,
                localidades=localidades
            )

        update(emp_id, data)
        log_audit(session, "update", "empleados", emp_id)

        password = (request.form.get("password") or "").strip()
        if password:
            update_password(emp_id, generate_password_hash(password))
            log_audit(session, "update_password", "empleados", emp_id)

        return redirect(url_for("empleados.listado"))

    return render_template(
        "empleados/form.html",
        mode="edit",
        data=emp,
        password_required=False,
        empresas=empresas,
        sucursales=sucursales,
        sectores=sectores,
        puestos=puestos,
        localidades=localidades
    )


@empleados_bp.route("/activar/<int:emp_id>")
@role_required("admin", "rrhh")
def activar(emp_id):
    set_activo(emp_id, 1)
    log_audit(session, "activate", "empleados", emp_id)
    return redirect(url_for("empleados.listado"))


@empleados_bp.route("/desactivar/<int:emp_id>")
@role_required("admin", "rrhh")
def desactivar(emp_id):
    set_activo(emp_id, 0)
    log_audit(session, "deactivate", "empleados", emp_id)
    return redirect(url_for("empleados.listado"))

