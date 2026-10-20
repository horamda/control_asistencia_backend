"""Panel: mapa de control de fichadas (solo lectura). Donde ficho cada empleado y si quedo dentro del radio.

Permiso mapa_fichadas (ver): la ubicacion es un dato personal, por defecto solo admin y RR. HH."""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import ProgrammingError

from repositories import carga_repository as db
from services import mapa_fichadas_service as mapa
from web.auth.decorators import _cached_web_user, permission_required

web = Blueprint("mapa_fichadas", __name__, url_prefix="/mapa-fichadas")
FILTROS = ("sucursal_id", "empleado_id", "accion", "ver")


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo") or not user.get("empresa_id"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


@web.errorhandler(mapa.Error)
def invalido(error):
    flash(str(error), "error")
    return redirect(url_for("mapa_fichadas.index"))


@web.errorhandler(ProgrammingError)
def sin_migrar(error):
    if error.errno not in (1146, 1054):
        raise error
    return render_template("error.html", code=503, request_id=None,
                           message="El mapa de fichadas requiere su migración (20261019_gps_calidad); se aplica al "
                                   "reiniciar el servicio."), 503


@web.after_request
def privado(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@web.get("/")
@permission_required("mapa_fichadas", "ver")
def index():
    actor = who()
    desde, hasta = mapa.periodo(request.args)
    filtros = {k: request.args.get(k, "") for k in FILTROS}
    datos = mapa.fichadas(actor["empresa_id"], desde, hasta, filtros)
    with db.transaction(read_only=True) as c:
        sucursales = db.all_rows(c, "SELECT id, nombre FROM sucursales WHERE empresa_id = %s ORDER BY nombre", (actor["empresa_id"],))
        empleados = db.all_rows(c, """SELECT id, apellido, nombre, legajo FROM empleados WHERE empresa_id = %s AND activo = 1
                                      ORDER BY apellido, nombre""", (actor["empresa_id"],))
    return render_template("mapa_fichadas/index.html", datos=datos, filtros=filtros, sucursales=sucursales,
                           posicion_vieja_min=mapa.POSICION_VIEJA_S // 60,
                           empleados=empleados, mapa_json=dict(puntos=datos["puntos"], referencias=datos["referencias"]))
