"""Panel: horas trabajadas (jornada laboral, etapa B). Calculo desde los fichajes, solo lectura sobre ellos.

Permiso horas_jornada: ver (pantallas), editar (registrar un calculo), exportar (Excel). Ver docs/jornada_laboral.md."""

import calendar
import datetime as dt

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from repositories import carga_repository as db
from services import jornada_calculo_service as calc
from services import jornada_service as reglas
from services.table_export_service import build_attachment_response
from utils.audit import log_audit
from web.auth.decorators import _cached_web_user, permission_required

web = Blueprint("horas", __name__, url_prefix="/horas-jornada")
FILTROS = ("sucursal_id", "sector_id", "convenio_id")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo") or not user.get("empresa_id"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


@web.errorhandler(calc.Error)
def invalido(error):
    flash(str(error), "error")
    if getattr(error, "status", 400) == 404:
        return redirect(url_for("horas.resumen"))
    return redirect(url_for("horas.resumen", **_args_periodo(sin_rango=True)))


@web.errorhandler(ProgrammingError)
def sin_migrar(error):
    if error.errno not in (1146, 1054):
        raise error
    return render_template("error.html", code=503, request_id=None,
                           message="El cálculo de horas requiere sus migraciones (20261019_jornada_laboral y "
                                   "20261019_jornada_calculo); se aplican al reiniciar el servicio."), 503


@web.after_request
def privado(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@web.app_template_filter("hm")
def filtro_horas(minutos):
    return calc.horas(minutos)


def _periodo(fuente):
    """Mes (YYYY-MM, por defecto el actual) o un rango desde/hasta. -> (desde, hasta, mes)."""
    desde, hasta = fuente.get("desde"), fuente.get("hasta")
    if desde and hasta:
        try:
            return dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta), None
        except ValueError:
            raise calc.Error("Fechas inválidas.")
    hoy = calc._hoy()
    try:
        anio, mes = (int(x) for x in str(fuente.get("mes") or "").split("-"))
        primero = dt.date(anio, mes, 1)
    except ValueError:
        primero = hoy.replace(day=1)
    return primero, primero.replace(day=calendar.monthrange(primero.year, primero.month)[1]), primero.strftime("%Y-%m")


def _args_periodo(sin_rango=False):
    args = {k: request.values.get(k) for k in ("mes", *FILTROS) if request.values.get(k)}
    if not sin_rango:
        args.update({k: request.values.get(k) for k in ("desde", "hasta") if request.values.get(k)})
    return args


def _opciones(empresa_id):
    with db.transaction(read_only=True) as c:
        return dict(
            sucursales=db.all_rows(c, "SELECT id, nombre FROM sucursales WHERE empresa_id = %s ORDER BY nombre", (empresa_id,)),
            sectores=db.all_rows(c, "SELECT id, nombre FROM sectores WHERE empresa_id = %s ORDER BY nombre", (empresa_id,)),
            convenios=reglas.convenios(empresa_id, solo_activos=True),
        )


def _cambios(datos, huellas):
    """Dias cuyas marcas cambiaron desde el calculo registrado (o que no estaban en el)."""
    return sum(1 for r in datos["empleados"] for d in r["dias"]
               if huellas.get((int(r["empleado"]["id"]), d["fecha"])) != d["huella"])


def _comunes():
    return dict(ESTADOS=calc.ESTADOS, TIPOS_DIA=calc.TIPOS_DIA, DIAS_CORTOS=calc.DIAS_CORTOS)


@web.get("/")
@permission_required("horas_jornada", "ver")
def resumen():
    actor = who()
    desde, hasta, mes = _periodo(request.args)
    filtros = {k: request.args.get(k, "") for k in FILTROS}
    datos = calc.calcular(actor["empresa_id"], desde, hasta, filtros)
    registrado, huellas = calc.ultimo_calculo(actor["empresa_id"], desde, hasta)
    return render_template("horas/resumen.html", datos=datos, mes=mes, filtros=filtros, registrado=registrado,
                           cambios=_cambios(datos, huellas) if registrado else None,
                           calculos=calc.calculos(actor["empresa_id"], 10), args=_args_periodo(),
                           **_opciones(actor["empresa_id"]), **_comunes())


@web.get("/empleado/<int:empleado_id>")
@permission_required("horas_jornada", "ver")
def empleado(empleado_id):
    actor = who()
    desde, hasta, mes = _periodo(request.args)
    datos = calc.calcular(actor["empresa_id"], desde, hasta, {"empleado_id": empleado_id})
    if not datos["empleados"]:
        raise calc.Error("Empleado no encontrado.", 404)
    fila = datos["empleados"][0]
    semanas = {s["cierre"]: s for s in fila["semanas"]}
    return render_template("horas/empleado.html", datos=datos, fila=fila, semanas=semanas, mes=mes,
                           args={k: v for k, v in _args_periodo().items() if k not in FILTROS}, **_comunes())


@web.post("/registrar")
@permission_required("horas_jornada", "editar")
def registrar():
    actor = who()
    desde, hasta, _ = _periodo(request.form)
    calculo_id, datos = calc.registrar(actor, desde, hasta, {k: request.form.get(k, "") for k in FILTROS},
                                       request.form.get("motivo"))
    log_audit(session, "horas_jornada_registrar", "jl_calculos", calculo_id)
    flash(f"Cálculo registrado: {len(datos['empleados'])} empleados, {datos['desde']:%d/%m} al {datos['hasta']:%d/%m}. "
          "Los cálculos anteriores se conservan.", "success")
    return redirect(url_for("horas.resumen", **_args_periodo()))


@web.get("/exportar")
@permission_required("horas_jornada", "exportar")
def exportar():
    actor = who()
    desde, hasta, _ = _periodo(request.args)
    datos = calc.calcular(actor["empresa_id"], desde, hasta, {k: request.args.get(k, "") for k in FILTROS})
    log_audit(session, "horas_jornada_exportar", "jl_calculos", None)
    return build_attachment_response(calc.exportar_xlsx(datos), filename=f"horas_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                                     mimetype=XLSX)

