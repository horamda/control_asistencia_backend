"""Panel: gestion de jornada laboral (etapa A): reglas generales, convenios, asignacion y condiciones de cada empleado.

Solo panel (sesion, CSRF y permiso jornada_laboral): no toca la API mobile ni la app. Ver docs/jornada_laboral.md."""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from repositories import carga_repository as db
from services import jornada_service as s
from utils.audit import log_audit
from web.auth.decorators import _cached_web_user, permission_required

web = Blueprint("jornada", __name__, url_prefix="/jornada-laboral")


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo") or not user.get("empresa_id"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


@web.errorhandler(s.Error)
def invalido(error):
    flash(str(error), "error")
    if getattr(error, "status", 400) == 404:
        return redirect(url_for("jornada.reglas"))
    return redirect(request.referrer or url_for("jornada.reglas"))


@web.errorhandler(ProgrammingError)
def sin_migrar(error):
    if error.errno not in (1146, 1054):
        raise error
    return render_template("error.html", code=503, request_id=None,
                           message="La gestión de jornada laboral requiere su migración (20261019_jornada_laboral); "
                                   "se aplica al reiniciar el servicio."), 503


@web.app_template_filter("jl_hhmm")
def filtro_hhmm(valor):
    """TIME de MySQL (timedelta), time o texto -> HH:MM para los campos de hora."""
    return s._hhmm(valor) or ""


@web.after_request
def privado(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _opciones(empresa_id):
    with db.transaction(read_only=True) as c:
        return dict(
            sucursales=db.all_rows(c, "SELECT id, nombre FROM sucursales WHERE empresa_id = %s ORDER BY nombre", (empresa_id,)),
            sectores=db.all_rows(c, "SELECT id, nombre FROM sectores WHERE empresa_id = %s ORDER BY nombre", (empresa_id,)),
            puestos=db.all_rows(c, "SELECT id, nombre FROM puestos WHERE empresa_id = %s ORDER BY nombre", (empresa_id,)),
        )


def _comunes():
    return dict(CAMPOS=s.CAMPOS, DIAS=s.DIAS, REGIMENES=s.REGIMENES, TIPOS_CONVENIO=s.TIPOS_CONVENIO, valores=s.valores,
                hoy=s._hoy().isoformat())


# --- Reglas generales (empresa y sucursales) -------------------------------------------------------------------

@web.get("/")
@permission_required("jornada_laboral", "ver")
def inicio():
    return redirect(url_for("jornada.reglas"))


@web.get("/reglas")
@permission_required("jornada_laboral", "ver")
def reglas():
    actor = who()
    return render_template("jornada/reglas.html", **s.vista_reglas(actor["empresa_id"]), **_comunes())


@web.post("/reglas")
@permission_required("jornada_laboral", "editar")
def guardar_regla_general():
    actor = who()
    alcance = "sucursal" if request.form.get("sucursal_id") else "empresa"
    rid = s.guardar_regla(actor, alcance, request.form.get("sucursal_id") or None, request.form)
    log_audit(session, f"jornada_regla_{alcance}", "jl_reglas", rid)
    flash("Regla guardada. Rige desde la fecha indicada; la versión anterior queda en el historial.", "success")
    return redirect(url_for("jornada.reglas"))


# --- Convenios y acuerdos -----------------------------------------------------------------------------------------

@web.get("/convenios")
@permission_required("jornada_laboral", "ver")
def convenios():
    return render_template("jornada/convenios.html", convenios=s.convenios(who()["empresa_id"]), **_comunes())


@web.post("/convenios")
@permission_required("jornada_laboral", "crear")
def crear_convenio():
    actor = who()
    cid = s.guardar_convenio(actor, request.form)
    log_audit(session, "jornada_convenio_crear", "jl_convenios", cid)
    flash("Convenio creado. Cargá su regla de jornada para que se apliquen sus topes.", "success")
    return redirect(url_for("jornada.convenio", convenio_id=cid))


@web.get("/convenios/<int:convenio_id>")
@permission_required("jornada_laboral", "ver")
def convenio(convenio_id):
    actor = who()
    lista = {c["id"]: c for c in s.convenios(actor["empresa_id"])}
    if convenio_id not in lista:
        raise s.Error("Convenio no encontrado.", 404)
    versiones = s.versiones(actor["empresa_id"], "convenio", convenio_id)
    vigente = next((v for v in versiones if v["vigente_desde"] <= s._hoy() and
                    (v["vigente_hasta"] is None or v["vigente_hasta"] >= s._hoy())), None)
    return render_template("jornada/convenio.html", convenio=lista[convenio_id], versiones=versiones, vigente=vigente,
                           **_comunes())


@web.post("/convenios/<int:convenio_id>")
@permission_required("jornada_laboral", "editar")
def editar_convenio(convenio_id):
    s.guardar_convenio(who(), request.form, convenio_id)
    log_audit(session, "jornada_convenio_editar", "jl_convenios", convenio_id)
    flash("Convenio actualizado.", "success")
    return redirect(url_for("jornada.convenio", convenio_id=convenio_id))


@web.post("/convenios/<int:convenio_id>/regla")
@permission_required("jornada_laboral", "editar")
def regla_convenio(convenio_id):
    rid = s.guardar_regla(who(), "convenio", convenio_id, request.form)
    log_audit(session, "jornada_regla_convenio", "jl_reglas", rid)
    flash("Regla del convenio guardada. Sus valores son los topes de los empleados con este convenio.", "success")
    return redirect(url_for("jornada.convenio", convenio_id=convenio_id))


# --- Asignacion de convenio (masiva) ------------------------------------------------------------------------------

@web.get("/asignaciones")
@permission_required("jornada_laboral", "ver")
def asignaciones():
    actor = who()
    filtros = {k: request.args.get(k, "") for k in ("sucursal_id", "sector_id", "puesto_id", "convenio_id", "q")}
    return render_template("jornada/asignaciones.html", empleados=s.empleados_para_asignar(actor["empresa_id"], filtros),
                           convenios=s.convenios(actor["empresa_id"], solo_activos=True), filtros=filtros,
                           **_opciones(actor["empresa_id"]), **_comunes())


@web.post("/asignaciones")
@permission_required("jornada_laboral", "editar")
def asignar():
    actor = who()
    asignados, errores = s.asignar_convenio(actor, request.form.getlist("empleado_id"), request.form.get("convenio_id"),
                                            request.form.get("vigente_desde"), request.form.get("motivo"))
    log_audit(session, "jornada_asignar_convenio", "jl_asignaciones", request.form.get("convenio_id"))
    if asignados:
        flash(f"Convenio asignado a {asignados} empleado{'' if asignados == 1 else 's'}.", "success")
    for e in errores[:10]:
        flash(f"{e.get('nombre') or e['empleado_id']}: {e['error']}.", "error")
    return redirect(url_for("jornada.asignaciones", **{k: v for k, v in request.args.items()}))


# --- Condiciones laborales de un empleado -------------------------------------------------------------------------

@web.get("/empleado/<int:empleado_id>")
@permission_required("jornada_laboral", "ver")
def empleado(empleado_id):
    actor = who()
    datos = s.condiciones(actor, empleado_id, request.args.get("fecha") or None)
    return render_template("jornada/empleado.html", **datos, convenios=s.convenios(actor["empresa_id"], solo_activos=True),
                           **_comunes())


@web.post("/empleado/<int:empleado_id>/regla")
@permission_required("jornada_laboral", "editar")
def regla_empleado(empleado_id):
    rid = s.guardar_regla(who(), "empleado", empleado_id, request.form)
    log_audit(session, "jornada_regla_empleado", "jl_reglas", rid)
    flash("Condición individual guardada.", "success")
    return redirect(url_for("jornada.empleado", empleado_id=empleado_id))


@web.post("/empleado/<int:empleado_id>/convenio")
@permission_required("jornada_laboral", "editar")
def convenio_empleado(empleado_id):
    actor = who()
    asignados, errores = s.asignar_convenio(actor, [empleado_id], request.form.get("convenio_id"),
                                            request.form.get("vigente_desde"), request.form.get("motivo"))
    log_audit(session, "jornada_asignar_convenio", "jl_asignaciones", empleado_id)
    if asignados:
        flash("Convenio asignado.", "success")
    for e in errores:
        flash(f"No se asignó: {e['error']}.", "error")
    return redirect(url_for("jornada.empleado", empleado_id=empleado_id))


# --- Historial ----------------------------------------------------------------------------------------------------

@web.get("/historial")
@permission_required("jornada_laboral", "ver")
def historial():
    return render_template("jornada/historial.html", filas=s.historial(who()["empresa_id"]), **_comunes())
