import datetime

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from repositories.empresa_repository import get_all as get_empresas
from repositories.sector_repository import get_page as get_sectores_page
from repositories.kpi_sectorial_repository import (
    copiar_objetivos_anio,
    create_kpi,
    delete_objetivo,
    get_kpi_by_id,
    get_kpis_by_sector,
    get_objetivos_by_sector_anio,
    tiene_objetivos_anio,
    toggle_kpi_activo,
    update_kpi,
    upsert_objetivo,
)
from services.kpi_sectorial_import_service import KpiImportError, importar_resultados_desde_csv
from utils.audit import log_audit
from web.auth.decorators import role_required

kpis_sectoriales_bp = Blueprint(
    "kpis_sectoriales",
    __name__,
    url_prefix="/kpis-sectoriales",
)

_TIPOS_ACUMULACION = ["suma", "promedio", "ultimo"]


def _year_options():
    y = datetime.date.today().year
    return list(range(y + 1, y - 4, -1))


def _get_sectores(empresa_id):
    if not empresa_id:
        return []
    rows, _ = get_sectores_page(1, 500, empresa_id=empresa_id, activo=1)
    return rows


# ---------------------------------------------------------------------------
# KPIs por sector — listado principal
# ---------------------------------------------------------------------------

@kpis_sectoriales_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    empresa_id = request.args.get("empresa_id", type=int)
    sector_id = request.args.get("sector_id", type=int)
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None

    empresas = get_empresas()
    sectores = _get_sectores(empresa_id)
    kpis = get_kpis_by_sector(sector_id) if sector_id else []

    return render_template(
        "kpis_sectoriales/listado.html",
        kpis=kpis,
        empresas=empresas,
        sectores=sectores,
        empresa_id=empresa_id,
        sector_id=sector_id,
        error=error,
        msg=msg,
    )


@kpis_sectoriales_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    empresas = get_empresas()
    empresa_id = request.args.get("empresa_id", type=int) or request.form.get("empresa_id", type=int)
    sectores = _get_sectores(empresa_id)
    error = None

    if request.method == "POST":
        empresa_id = request.form.get("empresa_id", type=int)
        sector_id = request.form.get("sector_id", type=int)
        codigo = (request.form.get("codigo") or "").strip().upper()
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = (request.form.get("descripcion") or "").strip() or None
        unidad = (request.form.get("unidad") or "").strip()
        tipo_acumulacion = (request.form.get("tipo_acumulacion") or "suma").strip()
        mayor_es_mejor = 1 if request.form.get("mayor_es_mejor") else 0

        if not empresa_id or not sector_id or not codigo or not nombre or not unidad:
            error = "Empresa, sector, codigo, nombre y unidad son obligatorios."
            sectores = _get_sectores(empresa_id)
        elif tipo_acumulacion not in _TIPOS_ACUMULACION:
            error = "Tipo de acumulacion invalido."
        else:
            try:
                kpi_id = create_kpi(empresa_id, sector_id, codigo, nombre, descripcion,
                                    unidad, tipo_acumulacion, mayor_es_mejor)
                log_audit(session, "crear", "kpis_definicion", kpi_id)
                return redirect(url_for("kpis_sectoriales.listado",
                                        empresa_id=empresa_id, sector_id=sector_id,
                                        msg="KPI creado correctamente."))
            except Exception as exc:
                current_app.logger.exception("kpi_create_error")
                sectores = _get_sectores(empresa_id)
                if "Duplicate entry" in str(exc) or "uk_kpis" in str(exc):
                    error = f"Ya existe un KPI con el codigo '{codigo}' en este sector."
                else:
                    error = "Error al guardar el KPI."

    return render_template(
        "kpis_sectoriales/form.html",
        empresas=empresas,
        sectores=sectores,
        tipos_acumulacion=_TIPOS_ACUMULACION,
        kpi=None,
        empresa_id=empresa_id,
        error=error,
    )


@kpis_sectoriales_bp.route("/<int:kpi_id>/editar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(kpi_id):
    kpi = get_kpi_by_id(kpi_id)
    if not kpi:
        return redirect(url_for("kpis_sectoriales.listado", error="KPI no encontrado."))

    empresas = get_empresas()
    sectores = _get_sectores(kpi["empresa_id"])
    error = None

    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip().upper()
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = (request.form.get("descripcion") or "").strip() or None
        unidad = (request.form.get("unidad") or "").strip()
        tipo_acumulacion = (request.form.get("tipo_acumulacion") or "suma").strip()
        mayor_es_mejor = 1 if request.form.get("mayor_es_mejor") else 0

        if not codigo or not nombre or not unidad:
            error = "Codigo, nombre y unidad son obligatorios."
        elif tipo_acumulacion not in _TIPOS_ACUMULACION:
            error = "Tipo de acumulacion invalido."
        else:
            try:
                update_kpi(kpi_id, codigo, nombre, descripcion, unidad, tipo_acumulacion, mayor_es_mejor)
                log_audit(session, "editar", "kpis_definicion", kpi_id)
                return redirect(url_for("kpis_sectoriales.listado",
                                        empresa_id=kpi["empresa_id"],
                                        sector_id=kpi["sector_id"],
                                        msg="KPI actualizado."))
            except Exception as exc:
                current_app.logger.exception("kpi_update_error")
                if "Duplicate entry" in str(exc) or "uk_kpis" in str(exc):
                    error = f"Ya existe un KPI con el codigo '{codigo}' en este sector."
                else:
                    error = "Error al actualizar el KPI."

    return render_template(
        "kpis_sectoriales/form.html",
        empresas=empresas,
        sectores=sectores,
        tipos_acumulacion=_TIPOS_ACUMULACION,
        kpi=kpi,
        empresa_id=kpi["empresa_id"],
        error=error,
    )


@kpis_sectoriales_bp.route("/<int:kpi_id>/toggle", methods=["POST"])
@role_required("admin", "rrhh")
def toggle(kpi_id):
    kpi = get_kpi_by_id(kpi_id)
    if not kpi:
        return redirect(url_for("kpis_sectoriales.listado", error="KPI no encontrado."))
    toggle_kpi_activo(kpi_id)
    log_audit(session, "toggle_activo", "kpis_definicion", kpi_id)
    return redirect(url_for("kpis_sectoriales.listado",
                             empresa_id=kpi["empresa_id"],
                             sector_id=kpi["sector_id"],
                             msg="Estado del KPI actualizado."))


# ---------------------------------------------------------------------------
# Objetivos — por sector y año (lista simple, no matriz)
# ---------------------------------------------------------------------------

@kpis_sectoriales_bp.route("/objetivos")
@role_required("admin", "rrhh")
def objetivos():
    empresa_id = request.args.get("empresa_id", type=int)
    sector_id = request.args.get("sector_id", type=int)
    anio = request.args.get("anio", type=int) or datetime.date.today().year
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None

    empresas = get_empresas()
    sectores = _get_sectores(empresa_id)
    kpis_con_objetivo = get_objetivos_by_sector_anio(sector_id, anio) if sector_id else []

    sector_nombre = next((s["nombre"] for s in sectores if s["id"] == sector_id), None)
    puede_copiar = sector_id is not None and tiene_objetivos_anio(sector_id, anio - 1)

    return render_template(
        "kpis_sectoriales/objetivos.html",
        empresas=empresas,
        sectores=sectores,
        kpis_con_objetivo=kpis_con_objetivo,
        empresa_id=empresa_id,
        sector_id=sector_id,
        sector_nombre=sector_nombre,
        anio=anio,
        years=_year_options(),
        puede_copiar_anio_anterior=puede_copiar,
        error=error,
        msg=msg,
    )


@kpis_sectoriales_bp.route("/objetivos/guardar", methods=["POST"])
@role_required("admin", "rrhh")
def guardar_objetivo():
    empresa_id = request.form.get("empresa_id", type=int)
    sector_id = request.form.get("sector_id", type=int)
    kpi_id = request.form.get("kpi_id", type=int)
    anio = request.form.get("anio", type=int)
    objetivo_str = (request.form.get("objetivo_valor") or "").strip().replace(",", ".")
    valor_min_str = (request.form.get("valor_min") or "").strip().replace(",", ".")
    valor_max_str = (request.form.get("valor_max") or "").strip().replace(",", ".")
    condicion = (request.form.get("condicion") or "gte").strip()
    action = (request.form.get("action") or "guardar").strip()

    redirect_back = url_for("kpis_sectoriales.objetivos",
                             empresa_id=empresa_id, sector_id=sector_id, anio=anio)

    if not all([empresa_id, sector_id, kpi_id, anio]):
        return redirect(redirect_back + "&error=Datos+incompletos.")

    if action == "eliminar":
        delete_objetivo(sector_id, kpi_id, anio)
        log_audit(session, "eliminar_objetivo", "kpis_sector_objetivo", kpi_id)
        return redirect(url_for("kpis_sectoriales.objetivos",
                                 empresa_id=empresa_id, sector_id=sector_id, anio=anio,
                                 msg="Objetivo eliminado."))

    objetivo_valor = None
    valor_min = None
    valor_max = None

    if condicion == "between":
        try:
            valor_min = float(valor_min_str)
            valor_max = float(valor_max_str)
            if valor_min >= valor_max:
                raise ValueError("min >= max")
        except (ValueError, TypeError):
            return redirect(url_for("kpis_sectoriales.objetivos",
                                     empresa_id=empresa_id, sector_id=sector_id, anio=anio,
                                     error="Rango invalido: minimo debe ser menor que maximo."))
    else:
        try:
            objetivo_valor = float(objetivo_str)
            if objetivo_valor < 0:
                raise ValueError("negativo")
        except (ValueError, TypeError):
            return redirect(url_for("kpis_sectoriales.objetivos",
                                     empresa_id=empresa_id, sector_id=sector_id, anio=anio,
                                     error="Valor de objetivo invalido."))

    upsert_objetivo(empresa_id, sector_id, kpi_id, anio, condicion, objetivo_valor, valor_min, valor_max)
    log_audit(session, "upsert_objetivo", "kpis_sector_objetivo", kpi_id)
    return redirect(url_for("kpis_sectoriales.objetivos",
                             empresa_id=empresa_id, sector_id=sector_id, anio=anio,
                             msg="Objetivo guardado."))


@kpis_sectoriales_bp.route("/objetivos/copiar-anio-anterior", methods=["POST"])
@role_required("admin", "rrhh")
def copiar_objetivos_anio_anterior():
    empresa_id = request.form.get("empresa_id", type=int)
    sector_id = request.form.get("sector_id", type=int)
    anio = request.form.get("anio", type=int)

    if not all([empresa_id, sector_id, anio]):
        return redirect(url_for("kpis_sectoriales.objetivos", empresa_id=empresa_id,
                                 sector_id=sector_id, anio=anio, error="Datos incompletos."))

    copiados = copiar_objetivos_anio(empresa_id, sector_id, anio - 1, anio)
    log_audit(session, "copiar_objetivos_anio", "kpis_sector_objetivo", sector_id)

    if copiados == 0:
        return redirect(url_for("kpis_sectoriales.objetivos", empresa_id=empresa_id,
                                 sector_id=sector_id, anio=anio,
                                 error=f"No hay objetivos en {anio - 1} para copiar."))

    return redirect(url_for("kpis_sectoriales.objetivos", empresa_id=empresa_id,
                             sector_id=sector_id, anio=anio,
                             msg=f"{copiados} objetivo(s) copiados de {anio - 1}."))


# ---------------------------------------------------------------------------
# Importar resultados diarios CSV
# ---------------------------------------------------------------------------

@kpis_sectoriales_bp.route("/importar-resultados", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def importar_resultados():
    empresas = get_empresas()
    resultado = None

    if request.method == "POST":
        empresa_id = request.form.get("empresa_id", type=int)
        archivo = request.files.get("archivo_csv")

        if not empresa_id:
            resultado = {"error": "Debe seleccionar una empresa."}
        elif not archivo or not str(archivo.filename or "").lower().endswith(".csv"):
            resultado = {"error": "Debe subir un archivo .csv valido."}
        else:
            try:
                resultado = importar_resultados_desde_csv(empresa_id, archivo.stream)
                log_audit(session, "importar_resultados_csv", "kpis_empleado_resultado", 0)
            except KpiImportError as exc:
                resultado = {"error": str(exc)}
            except Exception as exc:
                current_app.logger.exception("kpi_import_resultados_error")
                resultado = {"error": f"Error al procesar el archivo: {exc}"}

    return render_template(
        "kpis_sectoriales/importar_resultados.html",
        empresas=empresas,
        resultado=resultado,
    )
