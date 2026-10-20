import logging
from web.facial_draft_forms import prepare_facial_form

from web.auth.decorators import permission_required, require_company_record
import datetime

from flask import Blueprint, render_template, redirect, url_for, request, abort, session, jsonify, flash
from web.auth.decorators import role_required
from utils.forms import parse_float as _parse_float, parse_int as _parse_int
from repositories.sucursal_repository import (
    get_all,
    get_by_id,
    create,
    update,
    set_activa
)
from repositories.empresa_repository import get_all as get_empresas
from utils.audit import log_audit
from services import sucursal_geo_service as geo
from services import geocodificacion_service as geocodificacion

sucursales_bp = Blueprint("sucursales", __name__, url_prefix="/sucursales")


def _geo(sucursal):
    """Sugerencia desde las fichadas, QR activos y la correccion de fichadas anteriores (solo para editar; nunca
    rompe el formulario)."""
    try:
        datos = geo.contexto(sucursal)
    except Exception:
        logging.getLogger(__name__).warning("sucursal_geo_error", exc_info=True)
        return None
    hoy = geo.now_local().date()
    desde = request.args.get("corr_desde") or (hoy - datetime.timedelta(days=90)).isoformat()
    hasta = request.args.get("corr_hasta") or hoy.isoformat()
    try:
        datos["correccion"] = geo.vista_correccion(sucursal, desde, hasta)
        datos["correcciones"] = geo.correcciones(sucursal["id"])
    except geo.CorreccionError as error:
        datos["correccion_error"] = str(error)
    except Exception:
        logging.getLogger(__name__).warning("sucursal_geo_correccion_error", exc_info=True)
    return datos



def _extract_form_data(form):
    return {
        "empresa_id": _parse_int(form.get("empresa_id")),
        "nombre": (form.get("nombre") or "").strip(),
        "direccion": (form.get("direccion") or "").strip(),
        "latitud": _parse_float(form.get("latitud")),
        "longitud": _parse_float(form.get("longitud")),
        "radio_permitido_m": _parse_int(form.get("radio_permitido_m")),
        "activa": form.get("activa") == "1"
    }


def _validate_form(form):
    errors = []
    if not (form.get("empresa_id") or "").strip():
        errors.append("Empresa es requerida.")
    if not (form.get("nombre") or "").strip():
        errors.append("Nombre es requerido.")

    for field, label in [
        ("empresa_id", "Empresa"),
        ("radio_permitido_m", "Radio permitido")
    ]:
        value = (form.get(field) or "").strip()
        if value and not value.isdigit():
            errors.append(f"{label} debe ser numérico.")

    for field, label in [
        ("latitud", "Latitud"),
        ("longitud", "Longitud")
    ]:
        value = (form.get(field) or "").strip()
        if value:
            try:
                float(value)
            except ValueError:
                errors.append(f"{label} debe ser numérico.")

    return errors


@sucursales_bp.route("/")
@role_required("admin")
def listado():
    sucursales = get_all(include_inactive=True)
    return render_template("sucursales/listado.html", sucursales=sucursales)


@sucursales_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin")
def nuevo():
    empresas = get_empresas()
    if request.method == "POST":
        errors = _validate_form(request.form)
        data = _extract_form_data(request.form)
        if errors:
            return render_template(
                "sucursales/form.html",
                mode="new",
                data=data,
                errors=errors,
                empresas=empresas
            )

        suc_id = create(data)
        log_audit(session, "create", "sucursales", suc_id)
        return redirect(url_for("sucursales.listado"))

    return render_template(
        "sucursales/form.html",
        mode="new",
        data={},
        empresas=empresas
    )


@sucursales_bp.route("/editar/<int:sucursal_id>", methods=["GET", "POST"])
@role_required("admin")
def editar(sucursal_id):
    suc = get_by_id(sucursal_id)
    if not suc:
        abort(404)
    facial_result = prepare_facial_form(
        suc, scope="branch", return_url=url_for("sucursales.editar", sucursal_id=sucursal_id))
    if facial_result is not None and facial_result is not False:
        return facial_result

    empresas = get_empresas(include_inactive=True)

    if request.method == "POST" and facial_result is None:
        errors = _validate_form(request.form)
        data = _extract_form_data(request.form)
        if errors:
            merged = dict(suc)
            merged.update(data)
            return render_template(
                "sucursales/form.html",
                mode="edit",
                data=merged,
                errors=errors,
                empresas=empresas,
                geo=_geo(suc),
            )

        update(sucursal_id, data)
        log_audit(session, "update", "sucursales", sucursal_id)
        return redirect(url_for("sucursales.listado"))

    return render_template(
        "sucursales/form.html",
        mode="edit",
        data=suc,
        empresas=empresas,
        geo=_geo(suc),
    )


@sucursales_bp.route("/<int:sucursal_id>/corregir-fichadas", methods=["POST"])
@role_required("admin")
def corregir_fichadas(sucursal_id):
    """Recalcula las fichadas que se validaron contra una ubicacion anterior de la sucursal (guarda lo anterior)."""
    suc = get_by_id(sucursal_id)
    if not suc:
        abort(404)
    try:
        resultado = geo.corregir(dict(user_id=session.get("user_id")), suc, request.form.get("desde"),
                                 request.form.get("hasta"), request.form.get("motivo"))
    except geo.CorreccionError as error:
        flash(str(error), "error")
    else:
        log_audit(session, "corregir_geo_fichadas", "sucursales", sucursal_id)
        flash(f"Fichadas corregidas: {resultado['corregidas']}. Pasaron a dentro del radio: {resultado['pasan_a_dentro']}. "
              f"Intentos de fraude anulados: {resultado['eventos_anulados']}. Los valores anteriores quedan guardados.",
              "success")
    return redirect(url_for("sucursales.editar", sucursal_id=sucursal_id,
                            corr_desde=request.form.get("desde"), corr_hasta=request.form.get("hasta")))


@sucursales_bp.route("/geocodificar")
@role_required("admin")
def geocodificar():
    """Buscador de direcciones del formulario (lo consulta el mapa; el navegador no puede llamar a otros sitios)."""
    try:
        return jsonify(resultados=geocodificacion.buscar(request.args.get("q")))
    except geocodificacion.Error as error:
        return jsonify(error=str(error)), getattr(error, "status", 400)


@sucursales_bp.route("/activar/<int:sucursal_id>", methods=["POST"])
@permission_required("sucursales", "aprobar")
def activar(sucursal_id):
    require_company_record(get_by_id(sucursal_id))
    set_activa(sucursal_id, 1)
    log_audit(session, "activate", "sucursales", sucursal_id)
    return redirect(url_for("sucursales.listado"))


@sucursales_bp.route("/desactivar/<int:sucursal_id>", methods=["POST"])
@permission_required("sucursales", "aprobar")
def desactivar(sucursal_id):
    require_company_record(get_by_id(sucursal_id))
    set_activa(sucursal_id, 0)
    log_audit(session, "deactivate", "sucursales", sucursal_id)
    return redirect(url_for("sucursales.listado"))
