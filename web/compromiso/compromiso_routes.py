"""Panel: indice de compromiso (engagement) por año, sucursal y area. Carga desde planilla o a mano."""
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from services import compromiso_service as compromiso
from utils.audit import log_audit
from web.auth.decorators import permission_required
from web.carga.carga_routes import scope

compromiso_bp = Blueprint("compromiso", __name__, url_prefix="/compromiso")


def _anio_pedido(disponibles):
    try:
        return compromiso._anio(request.values.get("anio")) if request.values.get("anio") else (
            disponibles[0] if disponibles else compromiso.now_local().year)
    except compromiso.CompromisoError:
        return disponibles[0] if disponibles else compromiso.now_local().year


@compromiso_bp.get("/")
@permission_required("compromiso", "ver")
def index():
    empresa_id, empresas = scope()
    disponibles = compromiso.anios(empresa_id)
    anio = _anio_pedido(disponibles)
    sucursales, sectores = compromiso.catalogo(empresa_id)
    anios_menu = sorted(set(disponibles) | {anio, compromiso.now_local().year}, reverse=True)
    return render_template("compromiso/index.html", empresa_id=empresa_id, empresas=empresas, anio=anio,
                           anios=anios_menu, datos=compromiso.listado(empresa_id, anio),
                           sucursales=sucursales, sectores=sectores)


@compromiso_bp.post("/guardar")
@permission_required("compromiso", "editar")
def guardar():
    empresa_id, _ = scope()
    try:
        anio = compromiso.guardar(empresa_id, session.get("user_id"), request.form.get("anio"),
                                  request.form.get("sucursal_id"), request.form.get("sector_id"), request.form.get("indice"))
    except compromiso.CompromisoError as exc:
        flash(str(exc), "error")
        return redirect(url_for("compromiso.index", empresa_id=empresa_id, anio=request.form.get("anio")))
    log_audit(session, "guardar", "compromiso_indices", None)
    flash("Índice guardado.", "success")
    return redirect(url_for("compromiso.index", empresa_id=empresa_id, anio=anio))


@compromiso_bp.post("/<int:fila_id>/eliminar")
@permission_required("compromiso", "eliminar")
def eliminar(fila_id):
    empresa_id, _ = scope()
    try:
        compromiso.borrar(empresa_id, fila_id)
        log_audit(session, "eliminar", "compromiso_indices", fila_id)
        flash("Fila eliminada.", "success")
    except compromiso.CompromisoError as exc:
        flash(str(exc), "error")
    return redirect(url_for("compromiso.index", empresa_id=empresa_id, anio=request.form.get("anio")))


@compromiso_bp.post("/importar")
@permission_required("compromiso", "crear")
def importar():
    empresa_id, _ = scope()
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Elegí la planilla a importar.", "error")
        return redirect(url_for("compromiso.index", empresa_id=empresa_id))
    try:
        resultado = compromiso.importar(empresa_id, session.get("user_id"), archivo.filename, archivo.read(5 * 1024 * 1024 + 1))
    except compromiso.CompromisoError as exc:
        flash(str(exc), "error")
        return redirect(url_for("compromiso.index", empresa_id=empresa_id))
    log_audit(session, "importar", "compromiso_indices", None)
    flash(f"Importadas {resultado['filas']} filas ({', '.join(str(a) for a in resultado['anios'])}).", "success")
    return redirect(url_for("compromiso.index", empresa_id=empresa_id, anio=resultado["anios"][-1]))


@compromiso_bp.get("/plantilla.xlsx")
@permission_required("compromiso", "ver")
def plantilla():
    empresa_id, _ = scope()
    disponibles = compromiso.anios(empresa_id)
    contenido = compromiso.plantilla(empresa_id, _anio_pedido(disponibles))
    return Response(contenido, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="indice_compromiso.xlsx"'})
