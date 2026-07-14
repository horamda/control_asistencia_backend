import datetime

from flask import Blueprint, render_template, redirect, url_for, request, abort, session, current_app, Response
from werkzeug.security import generate_password_hash
import time
from utils.forms import parse_int as _parse_int, safe_next_url as _safe_next_url
from services.empleado_export_service import exportar_empleados_excel
from services.empleado_import_service import importar_desde_csv
from services.empleado_template_service import generar_template_excel
from services.vacaciones_service import VacacionesError, calcular_resumen_vacaciones

from repositories.empleado_repository import (
    create,
    exists_unique,
    get_all as get_empleados_all,
    get_by_id,
    get_page,
    set_activo,
    update,
    update_password,
)
from repositories.empleado_puesto_repository import (
    get_puestos_ids_by_empleado,
    replace_for_empleado as replace_puestos_adicionales,
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
        "foto": None,
        # Nuevos campos
        "cuil": (form.get("cuil") or "").strip(),
        "tipo_contrato": (form.get("tipo_contrato") or "").strip() or None,
        "modalidad": (form.get("modalidad") or "presencial").strip(),
        "fecha_baja": (form.get("fecha_baja") or "").strip() or None,
        "categoria": (form.get("categoria") or "").strip() or None,
        "obra_social": (form.get("obra_social") or "").strip() or None,
        "cod_chess_erp": _parse_int(form.get("cod_chess_erp")),
        "banco": (form.get("banco") or "").strip() or None,
        "cbu": (form.get("cbu") or "").strip() or None,
        "numero_emergencia": (form.get("numero_emergencia") or "").strip() or None,
        "puestos_adicionales_ids": _parse_int_list(form.getlist("puestos_adicionales_ids")),
        "reporta_a_empleado_id": _parse_int(form.get("reporta_a_empleado_id")),
    }


def _parse_int_list(values):
    ids = []
    seen = set()
    for value in values or []:
        parsed = _parse_int(value)
        if not parsed or parsed in seen:
            continue
        seen.add(parsed)
        ids.append(parsed)
    return ids


def _is_checked(value):
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "si", "s"}


def _resolve_photo_from_request(data, emp_actual=None):
    foto = str((emp_actual or {}).get("foto") or "").strip() or None

    foto_file = request.files.get("foto_file") or request.files.get("foto")
    has_file = bool(foto_file and str(foto_file.filename or "").strip())
    eliminar_foto = _is_checked(request.form.get("eliminar_foto"))

    if has_file and eliminar_foto:
        raise ValueError("No puede enviar una foto y marcar eliminar foto al mismo tiempo.")

    dni_nuevo = str(data.get("dni") or "").strip() or None
    dni_actual = str((emp_actual or {}).get("dni") or "").strip() or None
    dni_para_foto = dni_nuevo or dni_actual

    if has_file:
        if not dni_para_foto:
            raise ValueError("Debe ingresar DNI valido para asociar la foto.")
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


def _validate_puestos_adicionales(data, puestos):
    errors = []
    empresa_id = data.get("empresa_id")
    puesto_principal_id = data.get("puesto_id")
    puestos_adicionales_ids = data.get("puestos_adicionales_ids") or []
    puestos_by_id = {
        int(p.get("id")): p
        for p in puestos
        if p.get("id") is not None
    }

    for puesto_id in puestos_adicionales_ids:
        if puesto_principal_id and int(puesto_id) == int(puesto_principal_id):
            errors.append("El puesto principal no debe repetirse como puesto adicional.")
            continue
        puesto = puestos_by_id.get(int(puesto_id))
        if not puesto:
            errors.append("Puesto adicional invalido.")
            continue
        if empresa_id and int(puesto.get("empresa_id") or 0) != int(empresa_id):
            errors.append("Los puestos adicionales deben pertenecer a la misma empresa.")
    return errors


def _save_puestos_adicionales(emp_id, data):
    replace_puestos_adicionales(
        emp_id,
        empresa_id=data.get("empresa_id"),
        sector_id=data.get("sector_id"),
        puesto_ids=data.get("puestos_adicionales_ids") or [],
        puesto_principal_id=data.get("puesto_id"),
    )


def _get_empleados_lista_para_form():
    try:
        return get_empleados_all(include_inactive=False)
    except Exception:
        current_app.logger.warning("empleados_form_lista_error", exc_info=True)
        return []


def _vacaciones_resumen_para_empleado(empleado, anio: int) -> dict | None:
    try:
        emp_id = int((empleado or {}).get("id"))
    except (TypeError, ValueError):
        return None

    try:
        resumen = calcular_resumen_vacaciones(emp_id, anio)
        vac = resumen.get("vacaciones") or {}
        return {
            "anio": int(resumen.get("anio") or anio),
            "base": vac.get("dias_base", 0),
            "corresponden": vac.get("dias_corresponden", 0),
            "tomados": vac.get("dias_tomados", 0),
            "disponibles": vac.get("dias_disponibles", 0),
            "disponibles_con_pendientes": vac.get("dias_disponibles_con_pendientes", 0),
            "pendientes": vac.get("dias_pendientes", 0),
        }
    except VacacionesError:
        return None
    except Exception:
        current_app.logger.warning(
            "empleados_vacaciones_resumen_error",
            extra={"extra": {"empleado_id": emp_id, "anio": anio}},
            exc_info=True,
        )
        return None


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
    anio_vacaciones = datetime.date.today().year
    for empleado in empleados:
        empleado["vacaciones_resumen"] = _vacaciones_resumen_para_empleado(empleado, anio_vacaciones)

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
        errors.extend(_validate_puestos_adicionales(data, puestos))

        try:
            data["foto"] = _resolve_photo_from_request(data, emp_actual=None)
        except ValueError as exc:
            errors.append(str(exc))
        except RuntimeError as exc:
            current_app.logger.warning(
                "web_profile_photo_upload_error",
                extra={"extra": {"dni": data.get("dni"), "error": str(exc)}},
            )
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
                empleados_lista=_get_empleados_lista_para_form(),
                photo_cache_buster=int(time.time()),
            )

        password = (request.form.get("password") or "").strip()
        data["password_hash"] = generate_password_hash(password)

        emp_id = create(data)
        _save_puestos_adicionales(emp_id, data)
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
        empleados_lista=_get_empleados_lista_para_form(),
        photo_cache_buster=int(time.time()),
    )


@empleados_bp.route("/editar/<int:emp_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(emp_id):
    emp = get_by_id(emp_id)
    if not emp:
        abort(404)
    next_url = _safe_next_url(request.values.get("next"))
    emp["puestos_adicionales_ids"] = get_puestos_ids_by_empleado(emp_id)

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
        errors.extend(_validate_puestos_adicionales(data, puestos))
        try:
            data["foto"] = _resolve_photo_from_request(data, emp_actual=emp)
        except ValueError as exc:
            errors.append(str(exc))
        except RuntimeError as exc:
            current_app.logger.warning(
                "web_profile_photo_upload_error",
                extra={"extra": {"emp_id": emp_id, "dni": data.get("dni"), "error": str(exc)}},
            )
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
                empleados_lista=_get_empleados_lista_para_form(),
                photo_cache_buster=int(time.time()),
            )

        update(emp_id, data)
        _save_puestos_adicionales(emp_id, data)
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
        empleados_lista=_get_empleados_lista_para_form(),
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


@empleados_bp.route("/exportar")
@role_required("admin", "rrhh")
def exportar():
    empresa_id = request.args.get("empresa_id", type=int) or None
    activo_raw = str(request.args.get("activo") or "all").strip().lower()
    if activo_raw == "1":
        activo = 1
    elif activo_raw == "0":
        activo = 0
    else:
        activo = None

    try:
        excel_bytes = exportar_empleados_excel(empresa_id=empresa_id, activo=activo)
    except Exception as exc:
        current_app.logger.exception("exportar_empleados_error")
        return Response(f"Error al generar la exportacion: {exc}", status=500, mimetype="text/plain")

    import datetime
    fecha = datetime.date.today().strftime("%Y%m%d")
    filename = f"empleados_{fecha}.xlsx"
    return Response(
        excel_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@empleados_bp.route("/importar-csv", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def importar_csv():
    resultado = None

    if request.method == "POST":
        archivo = request.files.get("archivo_csv")
        empresa_id = _parse_int(request.form.get("empresa_id"))

        if not archivo or not archivo.filename.endswith(".csv"):
            resultado = {"error": "Debe subir un archivo .csv válido."}
        elif not empresa_id:
            resultado = {"error": "Debe seleccionar una empresa."}
        else:
            try:
                resultado = importar_desde_csv(archivo.stream, empresa_id)
                log_audit(session, "importar_csv", "empleados", empresa_id)
            except Exception as exc:
                current_app.logger.exception("importar_csv_error")
                resultado = {"error": f"Error al procesar el archivo: {exc}"}

    empresas = get_empresas(include_inactive=False)
    return render_template(
        "empleados/importar_csv.html",
        empresas=empresas,
        resultado=resultado,
    )


@empleados_bp.route("/importar-csv/template")
@role_required("admin", "rrhh")
def descargar_template_csv():
    try:
        excel_bytes = generar_template_excel()
    except Exception as exc:
        current_app.logger.exception("template_excel_error")
        return Response(
            f"Error al generar el template: {exc}",
            status=500,
            mimetype="text/plain",
        )
    return Response(
        excel_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=template_empleados.xlsx"},
    )
