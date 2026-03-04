from flask import Blueprint, render_template, redirect, url_for, request, abort, session, current_app
from werkzeug.security import generate_password_hash
import time
from urllib.parse import urlparse

from repositories.empleado_repository import (
    create,
    exists_unique,
    get_by_id,
    get_page,
    set_activo,
    update,
    update_password,
)
from repositories.empresa_repository import get_all as get_empresas
from repositories.localidad_repository import exists_codigo, get_all as get_localidades
from repositories.puesto_repository import get_all as get_puestos
from repositories.sector_repository import get_all as get_sectores
from repositories.sucursal_repository import get_all as get_sucursales
from services.profile_photo_service import delete_profile_photo_for_dni, upload_profile_photo
from utils.audit import log_audit
from utils.validators import EmpleadoValidator
from web.auth.decorators import role_required

empleados_bp = Blueprint("empleados", __name__, url_prefix="/empleados")


def _parse_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_next_url(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return None
    if not raw.startswith("/"):
        return None
    return raw


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
        "foto": (form.get("foto") or "").strip(),
    }


def _is_checked(value):
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "si", "s"}


def _resolve_photo_from_request(data, emp_actual=None):
    manual_url = str(data.get("foto") or "").strip() or None
    foto = manual_url

    foto_file = request.files.get("foto_file") or request.files.get("foto")
    has_file = bool(foto_file and str(foto_file.filename or "").strip())
    eliminar_foto = _is_checked(request.form.get("eliminar_foto"))

    if has_file and eliminar_foto:
        raise ValueError("No puede enviar una foto y marcar eliminar foto al mismo tiempo.")

    dni_nuevo = str(data.get("dni") or "").strip() or None
    dni_actual = str((emp_actual or {}).get("dni") or "").strip() or None
    dni_para_foto = dni_nuevo or dni_actual

    if has_file:
        try:
            foto = upload_profile_photo(foto_file, dni_para_foto)
            if emp_actual and dni_actual and dni_nuevo and dni_actual != dni_nuevo:
                # Si cambia DNI, intentamos limpiar archivo legacy para evitar huerfanos.
                delete_profile_photo_for_dni(dni_actual)
        except ValueError:
            raise
        except RuntimeError as exc:
            raise RuntimeError("No se pudo subir la foto de perfil.") from exc
    elif eliminar_foto:
        foto = None
        try:
            delete_profile_photo_for_dni(dni_para_foto)
        except ValueError:
            # Sin FTP configurado, limpiamos solo en DB para no bloquear.
            pass
        except RuntimeError:
            current_app.logger.warning(
                "web_profile_photo_delete_ftp_error",
                extra={"extra": {"dni": dni_para_foto, "empleado_id": (emp_actual or {}).get("id")}},
            )

    return foto


@empleados_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    if per_page not in {10, 20, 50, 100}:
        per_page = 20
    search = request.args.get("q")
    empresa_id = request.args.get("empresa_id", type=int)
    activo_raw = str(request.args.get("activo") or "all").strip().lower()
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    else:
        activo = None
        activo_raw = "all"
    empleados, total = get_page(
        page,
        per_page,
        include_inactive=True,
        search=search,
        empresa_id=empresa_id,
        activo=activo,
    )
    return_to = url_for(
        "empleados.listado",
        page=page,
        per=per_page,
        q=search or None,
        empresa_id=empresa_id,
        activo=(activo_raw if activo_raw != "all" else None),
    )
    empresas = get_empresas(include_inactive=True)
    return render_template(
        "empleados/listado.html",
        empleados=empleados,
        empresas=empresas,
        empresa_id=empresa_id,
        q=search,
        page=page,
        per_page=per_page,
        total=total,
        activo=activo_raw,
        return_to=return_to,
        photo_cache_buster=int(time.time()),
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
        errors = validator.validate(
            request.form,
            require_password=True,
            emp_id=None,
            exists_unique=exists_unique,
            exists_codigo=exists_codigo,
        )
        data = _extract_form_data(request.form)

        try:
            data["foto"] = _resolve_photo_from_request(data, emp_actual=None)
        except (ValueError, RuntimeError) as exc:
            errors.append(str(exc))

        if errors:
            return render_template(
                "empleados/form.html",
                mode="new",
                data=data,
                errors=errors,
                password_required=True,
                password_change_requested=True,
                empresas=empresas,
                sucursales=sucursales,
                sectores=sectores,
                puestos=puestos,
                localidades=localidades,
                photo_cache_buster=int(time.time()),
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
        password_change_requested=True,
        empresas=empresas,
        sucursales=sucursales,
        sectores=sectores,
        puestos=puestos,
        localidades=localidades,
        photo_cache_buster=int(time.time()),
    )


@empleados_bp.route("/editar/<int:emp_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(emp_id):
    emp = get_by_id(emp_id)
    if not emp:
        abort(404)
    next_url = _safe_next_url(request.values.get("next"))

    empresas = get_empresas(include_inactive=True)
    sucursales = get_sucursales(include_inactive=True)
    sectores = get_sectores(include_inactive=True)
    puestos = get_puestos(include_inactive=True)
    localidades = get_localidades()

    if request.method == "POST":
        validator = EmpleadoValidator()
        errors = validator.validate(
            request.form,
            require_password=False,
            emp_id=emp_id,
            exists_unique=exists_unique,
            exists_codigo=exists_codigo,
        )
        data = _extract_form_data(request.form)
        try:
            data["foto"] = _resolve_photo_from_request(data, emp_actual=emp)
        except (ValueError, RuntimeError) as exc:
            errors.append(str(exc))
        password_change_requested = _is_checked(request.form.get("cambiar_password"))
        password = (request.form.get("password") or "").strip()
        if password_change_requested and not password:
            errors.append("Debe ingresar una contrasena para actualizarla.")

        if errors:
            merged = dict(emp)
            merged.update(data)
            return render_template(
                "empleados/form.html",
                mode="edit",
                data=merged,
                errors=errors,
                password_required=False,
                password_change_requested=password_change_requested,
                next_url=next_url,
                empresas=empresas,
                sucursales=sucursales,
                sectores=sectores,
                puestos=puestos,
                localidades=localidades,
                photo_cache_buster=int(time.time()),
            )

        update(emp_id, data)
        log_audit(session, "update", "empleados", emp_id)

        if password_change_requested:
            update_password(emp_id, generate_password_hash(password))
            log_audit(session, "update_password", "empleados", emp_id)

        return redirect(next_url or url_for("empleados.listado"))

    return render_template(
        "empleados/form.html",
        mode="edit",
        data=emp,
        password_required=False,
        password_change_requested=False,
        next_url=next_url,
        empresas=empresas,
        sucursales=sucursales,
        sectores=sectores,
        puestos=puestos,
        localidades=localidades,
        photo_cache_buster=int(time.time()),
    )


@empleados_bp.route("/activar/<int:emp_id>")
@role_required("admin", "rrhh")
def activar(emp_id):
    set_activo(emp_id, 1)
    log_audit(session, "activate", "empleados", emp_id)
    return redirect(_safe_next_url(request.args.get("next")) or url_for("empleados.listado"))


@empleados_bp.route("/desactivar/<int:emp_id>")
@role_required("admin", "rrhh")
def desactivar(emp_id):
    set_activo(emp_id, 0)
    log_audit(session, "deactivate", "empleados", emp_id)
    return redirect(_safe_next_url(request.args.get("next")) or url_for("empleados.listado"))
