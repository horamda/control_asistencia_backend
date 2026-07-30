import calendar
import datetime

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from repositories.empresa_repository import get_all as get_empresas
from repositories.sector_repository import get_page as get_sectores_page
from repositories.sucursal_repository import get_all as get_sucursales
from repositories.kpi_sectorial_repository import (
    copiar_objetivos_anio,
    create_kpi,
    delete_objetivo,
    delete_resultados_mes,
    get_empleados_by_sector_para_kpis,
    get_kpi_by_id,
    get_kpis_by_sector,
    get_objetivos_by_sector_anio,
    get_resultados_empleado_kpis_anio,
    tiene_objetivos_anio,
    toggle_kpi_activo,
    update_kpi,
    upsert_objetivo,
)
from services.kpi_sectorial_import_service import KpiImportError, importar_resultados_desde_csv
from services.export_excel_service import generar_kpis_resultados_excel
from utils.audit import log_audit
from web.auth.decorators import role_required

kpis_sectoriales_bp = Blueprint(
    "kpis_sectoriales",
    __name__,
    url_prefix="/kpis-sectoriales",
)

_TIPOS_ACUMULACION = ["suma", "promedio", "ultimo"]
_MONTH_NAMES = [
    "",
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
]
_CONDICION_SIMBOLO = {"gte": ">=", "lte": "<=", "eq": "=", "between": "entre"}
_SEMAFORO_BADGE = {"verde": "ok", "amarillo": "warning", "rojo": "danger", "gris": ""}
_SEMAFORO_TONE = {"verde": "ok", "amarillo": "warn", "rojo": "bad", "gris": "empty"}


def _year_options():
    y = datetime.date.today().year
    return list(range(y + 1, y - 4, -1))


def _month_options():
    return [{"value": i, "label": _MONTH_NAMES[i]} for i in range(1, 13)]


def _get_sectores(empresa_id):
    if not empresa_id:
        return []
    rows, _ = get_sectores_page(1, 500, empresa_id=empresa_id, activo=1)
    return rows


def _safe_year(value):
    today = datetime.date.today()
    try:
        year = int(value)
    except (TypeError, ValueError):
        return today.year
    if year < 2020 or year > today.year + 1:
        return today.year
    return year


def _safe_month(value):
    try:
        month = int(value)
    except (TypeError, ValueError):
        return datetime.date.today().month
    if month < 1 or month > 12:
        return datetime.date.today().month
    return month


def _parse_delete_period(anio_value, mes_value):
    today = datetime.date.today()
    try:
        anio = int(anio_value)
        mes = int(mes_value)
    except (TypeError, ValueError):
        return None, None, "Periodo invalido."
    if anio < 2020 or anio > today.year + 1 or mes < 1 or mes > 12:
        return None, None, "Periodo invalido."
    return anio, mes, None


def _as_float(value):
    if value is None:
        return None
    return float(value)


def _fmt_num(value):
    if value is None:
        return "-"
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _date_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)[:10]


def _days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def _month_bounds(year: int, month: int):
    start = datetime.date(year, month, 1)
    end = datetime.date(year, month, calendar.monthrange(year, month)[1])
    return start, end


def _elapsed_fraction(start: datetime.date, end: datetime.date) -> float:
    today = datetime.date.today()
    if start > today:
        return 0.0
    effective_end = min(end, today)
    days = max((effective_end - start).days + 1, 0)
    return days / _days_in_year(start.year)


def _aggregate_values(values, tipo_acumulacion: str):
    if not values:
        return None
    ordered = sorted(values, key=lambda item: item[0])
    nums = [float(item[1]) for item in ordered]
    if tipo_acumulacion == "promedio":
        return sum(nums) / len(nums)
    if tipo_acumulacion == "ultimo":
        return nums[-1]
    return sum(nums)


def _objetivo_label(kpi: dict, fraction: float = 1.0):
    condicion = kpi.get("condicion") or "gte"
    unidad = kpi.get("unidad") or ""
    if condicion == "between":
        valor_min = kpi.get("valor_min")
        valor_max = kpi.get("valor_max")
        if valor_min is None or valor_max is None:
            return "Sin objetivo"
        return f"entre {_fmt_num(valor_min)} y {_fmt_num(valor_max)} {unidad}".strip()

    objetivo = kpi.get("objetivo_anual")
    if objetivo is None:
        return "Sin objetivo"
    valor = float(objetivo)
    if kpi.get("tipo_acumulacion") == "suma":
        valor *= max(fraction, 0.0)
    simbolo = _CONDICION_SIMBOLO.get(condicion, ">=")
    return f"{simbolo} {_fmt_num(valor)} {unidad}".strip()


def _evaluar_resultado(valor, kpi: dict, fraction: float):
    if valor is None:
        return "gris", "Sin resultado cargado."

    condicion = kpi.get("condicion") or "gte"
    valor = float(valor)

    if condicion == "between":
        valor_min = kpi.get("valor_min")
        valor_max = kpi.get("valor_max")
        if valor_min is None or valor_max is None:
            return "gris", "Rango objetivo sin definir."
        valor_min = float(valor_min)
        valor_max = float(valor_max)
        rango = valor_max - valor_min
        margen = rango * 0.10 if rango > 0 else abs(valor_min) * 0.10
        if valor_min <= valor <= valor_max:
            return "verde", "Dentro del rango objetivo."
        distancia = min(abs(valor - valor_min), abs(valor - valor_max))
        if distancia <= margen:
            return "amarillo", "Cerca del rango objetivo."
        return "rojo", "Fuera del rango objetivo."

    objetivo = kpi.get("objetivo_anual")
    if objetivo is None or float(objetivo) <= 0:
        return "gris", "Sin objetivo definido."

    esperado = float(objetivo)
    if kpi.get("tipo_acumulacion") == "suma":
        esperado *= fraction
    if esperado <= 0:
        return "gris", "Sin periodo transcurrido para evaluar."

    ratio = valor / esperado
    if condicion == "gte":
        if ratio >= 0.90:
            return "verde", "En objetivo."
        if ratio >= 0.70:
            return "amarillo", "Debajo del ritmo esperado."
        return "rojo", "Muy por debajo del objetivo."
    if condicion == "lte":
        if ratio <= 1.10:
            return "verde", "Dentro del limite."
        if ratio <= 1.30:
            return "amarillo", "Sobre el limite esperado."
        return "rojo", "Muy por encima del limite."

    if 0.90 <= ratio <= 1.10:
        return "verde", "Dentro del valor esperado."
    if 0.75 <= ratio <= 1.25:
        return "amarillo", "Levemente fuera del objetivo."
    return "rojo", "Fuera del objetivo."


def _build_resultados_view(rows, anio: int, mes: int, kpi_id: int | None = None):
    month_start, month_end = _month_bounds(anio, mes)
    month_start_s = month_start.isoformat()
    month_end_s = month_end.isoformat()
    days_year = _days_in_year(anio)
    month_full_fraction = ((month_end - month_start).days + 1) / days_year
    month_eval_fraction = _elapsed_fraction(month_start, month_end)
    year_eval_fraction = _elapsed_fraction(datetime.date(anio, 1, 1), datetime.date(anio, 12, 31))

    kpis = {}
    for row in rows:
        rid = int(row["kpi_id"])
        if kpi_id and rid != kpi_id:
            continue
        if rid not in kpis:
            kpis[rid] = {
                "kpi_id": rid,
                "codigo": row["codigo"],
                "nombre": row["nombre"],
                "unidad": row["unidad"],
                "tipo_acumulacion": row["tipo_acumulacion"],
                "mayor_es_mejor": bool(row["mayor_es_mejor"]),
                "objetivo_anual": _as_float(row.get("objetivo_valor")),
                "condicion": row.get("condicion") or "gte",
                "valor_min": _as_float(row.get("valor_min")),
                "valor_max": _as_float(row.get("valor_max")),
                "values_year": [],
                "values_month": [],
            }

        fecha = _date_iso(row.get("fecha"))
        if not fecha or row.get("valor") is None:
            continue
        valor = float(row["valor"])
        kpis[rid]["values_year"].append((fecha, valor))
        if month_start_s <= fecha <= month_end_s:
            kpis[rid]["values_month"].append((fecha, valor))

    resumen = []
    daily = {}
    for kpi in kpis.values():
        valor_mes = _aggregate_values(kpi["values_month"], kpi["tipo_acumulacion"])
        valor_anio = _aggregate_values(kpi["values_year"], kpi["tipo_acumulacion"])
        sem_mes, msg_mes = _evaluar_resultado(valor_mes, kpi, month_eval_fraction)
        sem_anio, msg_anio = _evaluar_resultado(valor_anio, kpi, year_eval_fraction)

        target_eval = None
        if kpi["objetivo_anual"] is not None and kpi["tipo_acumulacion"] == "suma":
            target_eval = kpi["objetivo_anual"] * month_eval_fraction

        resumen.append({
            **kpi,
            "resultado_mes": round(valor_mes, 4) if valor_mes is not None else None,
            "resultado_anio": round(valor_anio, 4) if valor_anio is not None else None,
            "registros_mes": len(kpi["values_month"]),
            "registros_anio": len(kpi["values_year"]),
            "objetivo_anual_label": _objetivo_label(kpi, 1.0),
            "objetivo_mes_label": _objetivo_label(kpi, month_full_fraction),
            "objetivo_eval_label": _objetivo_label(kpi, month_eval_fraction),
            "objetivo_eval_valor": round(target_eval, 4) if target_eval is not None else None,
            "semaforo_mes": sem_mes,
            "semaforo_anio": sem_anio,
            "semaforo_mes_label": _SEMAFORO_BADGE.get(sem_mes, ""),
            "semaforo_anio_label": _SEMAFORO_BADGE.get(sem_anio, ""),
            "mensaje_mes": msg_mes,
            "mensaje_anio": msg_anio,
        })

        daily_fraction = 1 / days_year if kpi["tipo_acumulacion"] == "suma" else 1.0
        for fecha, valor in kpi["values_month"]:
            sem, msg = _evaluar_resultado(valor, kpi, daily_fraction)
            daily.setdefault(fecha, []).append({
                "kpi_id": kpi["kpi_id"],
                "codigo": kpi["codigo"],
                "nombre": kpi["nombre"],
                "valor": round(valor, 4),
                "valor_fmt": _fmt_num(valor),
                "unidad": kpi["unidad"],
                "semaforo": sem,
                "tone": _SEMAFORO_TONE.get(sem, "empty"),
                "objetivo_label": _objetivo_label(kpi, daily_fraction),
                "mensaje": msg,
            })

    weeks = _build_resultados_calendar(daily, month_start, month_end)
    total_celdas_con_datos = sum(1 for entries in daily.values() if entries)
    en_objetivo = sum(1 for item in resumen if item["semaforo_mes"] == "verde")
    alerta = sum(1 for item in resumen if item["semaforo_mes"] in {"amarillo", "rojo"})
    sin_datos = sum(1 for item in resumen if item["resultado_mes"] is None)

    daily_rows = []
    current_day = month_start
    while current_day <= month_end:
        fecha = current_day.isoformat()
        daily_rows.append({
            "fecha": fecha,
            "entries": sorted(daily.get(fecha, []), key=lambda item: item["nombre"]),
        })
        current_day += datetime.timedelta(days=1)

    return {
        "resumen": resumen,
        "calendar_weeks": weeks,
        "daily_rows": daily_rows,
        "month_label": f"{_MONTH_NAMES[mes]} {anio}",
        "totales": {
            "kpis": len(resumen),
            "dias_con_resultado": total_celdas_con_datos,
            "en_objetivo": en_objetivo,
            "alerta": alerta,
            "sin_datos": sin_datos,
        },
    }


def _build_resultados_calendar(daily, month_start: datetime.date, month_end: datetime.date):
    days = []
    cur = month_start
    while cur <= month_end:
        fecha = cur.isoformat()
        entries = sorted(daily.get(fecha, []), key=lambda item: item["nombre"])
        if entries:
            if any(item["semaforo"] == "rojo" for item in entries):
                tone = "bad"
            elif any(item["semaforo"] == "amarillo" for item in entries):
                tone = "warn"
            elif any(item["semaforo"] == "verde" for item in entries):
                tone = "ok"
            else:
                tone = "empty"
            tooltip = " | ".join(
                f"{item['nombre']} ({item['codigo']}): {item['valor_fmt']} {item['unidad']} ({item['mensaje']})"
                for item in entries
            )
        else:
            tone = "weekend" if cur.weekday() >= 5 else "empty"
            tooltip = f"{fecha} - Sin resultado"

        days.append({
            "date": fecha,
            "num": cur.day,
            "weekday": cur.weekday(),
            "entries": entries,
            "tone": tone,
            "tooltip": tooltip,
        })
        cur += datetime.timedelta(days=1)

    weeks = []
    week = [None] * days[0]["weekday"]
    for day in days:
        week.append(day)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)
    return weeks


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
# Resultados por empleado
# ---------------------------------------------------------------------------

@kpis_sectoriales_bp.route("/resultados")
@role_required("admin", "rrhh")
def resultados():
    empresa_id = request.args.get("empresa_id", type=int)
    sector_id = request.args.get("sector_id", type=int)
    sucursal_id = request.args.get("sucursal_id", type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    kpi_id = request.args.get("kpi_id", type=int)
    anio = _safe_year(request.args.get("anio"))
    mes = _safe_month(request.args.get("mes"))
    error = (request.args.get("error") or "").strip() or None
    msg = (request.args.get("msg") or "").strip() or None

    empresas = get_empresas()
    sectores = _get_sectores(empresa_id)
    sucursales = get_sucursales(include_inactive=True)
    empleados = (
        get_empleados_by_sector_para_kpis(empresa_id, sector_id, sucursal_id=sucursal_id)
        if empresa_id and sector_id
        else []
    )
    kpis = get_kpis_by_sector(sector_id, activo=1) if sector_id else []
    vista = None

    empleado = None
    if empleado_id:
        empleado = next((e for e in empleados if int(e["id"]) == empleado_id), None)
        if not empleado:
            error = "Empleado no encontrado para la empresa y sector seleccionados."
            empleado_id = None

    if kpi_id and not any(int(k["id"]) == kpi_id for k in kpis):
        kpi_id = None

    if empleado and kpis:
        rows = get_resultados_empleado_kpis_anio(empleado_id, sector_id, anio)
        vista = _build_resultados_view(rows, anio, mes, kpi_id=kpi_id)

    return render_template(
        "kpis_sectoriales/resultados.html",
        empresas=empresas,
        sectores=sectores,
        sucursales=sucursales,
        empleados=empleados,
        kpis=kpis,
        empresa_id=empresa_id,
        sector_id=sector_id,
        sucursal_id=sucursal_id,
        empleado_id=empleado_id,
        empleado=empleado,
        kpi_id=kpi_id,
        anio=anio,
        mes=mes,
        years=_year_options(),
        months=_month_options(),
        bulk_delete_confirmacion=f"{anio}-{mes:02d}",
        bulk_delete_month_label=f"{_MONTH_NAMES[mes]} {anio}",
        vista=vista,
        error=error,
        msg=msg,
    )


@kpis_sectoriales_bp.route("/resultados/export.xlsx")
@role_required("admin", "rrhh")
def resultados_export_xlsx():
    empresa_id = request.args.get("empresa_id", type=int)
    sector_id = request.args.get("sector_id", type=int)
    sucursal_id = request.args.get("sucursal_id", type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    kpi_id = request.args.get("kpi_id", type=int)
    anio = _safe_year(request.args.get("anio"))
    mes = _safe_month(request.args.get("mes"))

    empresas = get_empresas()
    sectores = _get_sectores(empresa_id)
    empleados = (
        get_empleados_by_sector_para_kpis(empresa_id, sector_id, sucursal_id=sucursal_id)
        if empresa_id and sector_id
        else []
    )
    kpis = get_kpis_by_sector(sector_id, activo=1) if sector_id else []

    empleado = None
    if empleado_id:
        empleado = next((e for e in empleados if int(e["id"]) == empleado_id), None)
        if not empleado:
            return redirect(url_for(
                "kpis_sectoriales.resultados",
                empresa_id=empresa_id,
                sector_id=sector_id,
                sucursal_id=sucursal_id or None,
                empleado_id="",
                kpi_id=kpi_id or None,
                anio=anio,
                mes=mes,
                error="Empleado no encontrado para la empresa y sector seleccionados.",
            ))

    if kpi_id and not any(int(k["id"]) == kpi_id for k in kpis):
        kpi_id = None

    if not empleado or not kpis:
        return redirect(url_for(
            "kpis_sectoriales.resultados",
            empresa_id=empresa_id,
            sector_id=sector_id,
            sucursal_id=sucursal_id or None,
            empleado_id=empleado_id or "",
            kpi_id=kpi_id or "",
            anio=anio,
            mes=mes,
            error="Seleccione una empresa, sector y empleado con KPIs para exportar.",
        ))

    rows = get_resultados_empleado_kpis_anio(empleado_id, sector_id, anio)
    vista = _build_resultados_view(rows, anio, mes, kpi_id=kpi_id)

    empresa_label = next((e.get("razon_social") for e in empresas if int(e.get("id") or 0) == int(empresa_id or 0)), None)
    sector_label = next((s.get("nombre") for s in sectores if int(s.get("id") or 0) == int(sector_id or 0)), None)
    empleado_label = f"{empleado.get('apellido') or ''} {empleado.get('nombre') or ''}".strip()
    kpi_label = next((k.get("nombre") for k in kpis if int(k.get("id") or 0) == int(kpi_id or 0)), None)

    workbook = generar_kpis_resultados_excel(
        empresa_label=empresa_label,
        sector_label=sector_label,
        empleado_label=empleado_label or None,
        kpi_label=kpi_label,
        anio=anio,
        mes=mes,
        vista=vista,
    )
    filename = f"kpis_resultados_{anio}_{mes:02d}_{datetime.date.today().isoformat()}.xlsx"
    return current_app.response_class(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@kpis_sectoriales_bp.route("/resultados/eliminar-mes", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar_resultados_mes():
    empresa_id = request.form.get("empresa_id", type=int)
    sector_id = request.form.get("sector_id", type=int)
    empleado_id = request.form.get("empleado_id", type=int)
    kpi_id = request.form.get("kpi_id", type=int)
    anio, mes, period_error = _parse_delete_period(request.form.get("anio"), request.form.get("mes"))

    redirect_params = {
        "empresa_id": empresa_id,
        "sector_id": sector_id,
        "empleado_id": empleado_id,
        "kpi_id": kpi_id,
        "anio": anio or request.form.get("anio"),
        "mes": mes or request.form.get("mes"),
    }
    redirect_params = {k: v for k, v in redirect_params.items() if v not in (None, "")}

    if not empresa_id or not sector_id or period_error:
        return redirect(url_for(
            "kpis_sectoriales.resultados",
            **redirect_params,
            error=period_error or "Empresa y sector son obligatorios para eliminar resultados.",
        ))

    confirmacion = (request.form.get("confirmacion") or "").strip()
    confirmacion_esperada = f"{anio}-{mes:02d}"
    if confirmacion != confirmacion_esperada:
        return redirect(url_for(
            "kpis_sectoriales.resultados",
            **redirect_params,
            error=f"Para eliminar el mes debe confirmar escribiendo {confirmacion_esperada}.",
        ))

    eliminados = delete_resultados_mes(
        empresa_id,
        sector_id,
        anio,
        mes,
        empleado_id=empleado_id,
        kpi_id=kpi_id,
    )
    log_audit(session, "eliminar_resultados_mes", "kpis_empleado_resultado", sector_id)
    return redirect(url_for(
        "kpis_sectoriales.resultados",
        **redirect_params,
        msg=f"{eliminados} resultado(s) eliminados de {_MONTH_NAMES[mes]} {anio}.",
    ))


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
