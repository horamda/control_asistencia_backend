import csv
import datetime
import io

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, session, url_for

from repositories.asistencia_marca_repository import create as create_marca
from repositories.asistencia_marca_repository import get_by_asistencia as get_marcas_by_asistencia
from repositories.asistencia_marca_repository import delete_by_id as delete_marca_by_id
from repositories.asistencia_marca_repository import get_by_id as get_marca_by_id
from repositories.asistencia_marca_repository import get_for_export_admin as get_marcas_admin_export
from repositories.asistencia_marca_repository import update_basic as update_marca_basic
from repositories.asistencia_marca_repository import get_page_admin as get_marcas_admin_page
from repositories.asistencia_marca_repository import backfill_from_asistencias as backfill_marcas
from repositories.configuracion_empresa_repository import get_by_empresa_id as get_configuracion_empresa_by_id
from repositories.asistencia_repository import create, delete, get_by_id, get_page, sync_from_asistencia_marcas, update
from repositories.empleado_repository import get_all as get_empleados
from repositories.empresa_repository import get_all as get_empresas
from repositories.sucursal_repository import get_all as get_sucursales
from utils.asistencia import generar_ausentes, generar_ausentes_rango, get_horario_esperado, validar_asistencia
from utils.audit import log_audit
from web.auth.decorators import role_required

asistencias_bp = Blueprint("asistencias", __name__, url_prefix="/asistencias")
DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN = 60


def _parse_float(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date_iso(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    datetime.date.fromisoformat(value)
    return value


def _parse_int(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return None


def _to_hhmm(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    if not text:
        return None
    candidates = [text]
    if len(text) >= 7 and text[1] == ":":
        candidates.append(f"0{text}")
    if len(text) == 4 and text[1] == ":":
        candidates.append(f"0{text}")
    if len(text) == 5:
        candidates.append(f"{text}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return parsed.strftime("%H:%M")
        except ValueError:
            continue
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return text[:5] if len(text) >= 5 else text


def _parse_hhmm(value: str | None):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Hora requerida. Use HH:MM.")
    candidates = [raw]
    if len(raw) == 5:
        candidates.append(f"{raw}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return parsed.strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError("Hora invalida. Use HH:MM.")


def _to_date_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _to_minutes(hhmm: str | None):
    if not hhmm:
        return None
    try:
        hours, mins = hhmm.split(":")
        return int(hours) * 60 + int(mins)
    except (ValueError, TypeError):
        return None


def _to_bool_flag(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "si", "s", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _get_intervalo_minimo_fichadas_min(config: dict | None):
    if not config:
        return DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN
    raw = config.get("intervalo_minimo_fichadas_minutos")
    if raw is None:
        return DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN


def _build_planilla_pares(marcas: list[dict], intervalo_minimo_fichadas: int):
    pares = []
    errores = []
    ultima_accion = None
    ultima_hora = None
    ingreso_pendiente = None

    for marca in marcas:
        accion = str(marca.get("accion") or "").strip().lower()
        hora = _to_hhmm(marca.get("hora"))
        asistencia_id = marca.get("asistencia_id")
        marca_id = marca.get("id")
        gps_ok = _to_bool_flag(marca.get("gps_ok"))
        hora_min = _to_minutes(hora)

        if accion not in {"ingreso", "egreso"}:
            continue

        if ultima_hora and hora_min is not None:
            ultima_hora_min = _to_minutes(ultima_hora)
            if ultima_hora_min is not None:
                delta = hora_min - ultima_hora_min
                if delta < 0:
                    errores.append(
                        f"Orden horario invalido entre {ultima_accion} {ultima_hora} y {accion} {hora}."
                    )
                elif intervalo_minimo_fichadas > 0 and delta < intervalo_minimo_fichadas:
                    errores.append(
                        f"Intervalo corto: {ultima_accion} {ultima_hora} -> {accion} {hora} ({delta} min)."
                    )

        if accion == "ingreso":
            if ingreso_pendiente:
                pares.append(
                    {
                        "ingreso": ingreso_pendiente["hora"],
                        "egreso": None,
                        "asistencia_id": ingreso_pendiente.get("asistencia_id"),
                        "ingreso_marca_id": ingreso_pendiente.get("marca_id"),
                        "ingreso_gps_ok": ingreso_pendiente.get("gps_ok"),
                        "egreso_marca_id": None,
                        "egreso_gps_ok": None,
                        "error": "Ingreso sin egreso.",
                    }
                )
                errores.append("Ingreso sin egreso.")
            ingreso_pendiente = {
                "hora": hora,
                "asistencia_id": asistencia_id,
                "marca_id": marca_id,
                "gps_ok": gps_ok,
            }
        else:
            if not ingreso_pendiente:
                pares.append(
                    {
                        "ingreso": None,
                        "egreso": hora,
                        "asistencia_id": asistencia_id,
                        "ingreso_marca_id": None,
                        "ingreso_gps_ok": None,
                        "egreso_marca_id": marca_id,
                        "egreso_gps_ok": gps_ok,
                        "error": "Egreso sin ingreso previo.",
                    }
                )
                errores.append("Egreso sin ingreso previo.")
            else:
                par_error = None
                ingreso_min = _to_minutes(ingreso_pendiente["hora"])
                if ingreso_min is not None and hora_min is not None and hora_min < ingreso_min:
                    par_error = "Egreso anterior al ingreso."
                    errores.append(par_error)
                pares.append(
                    {
                        "ingreso": ingreso_pendiente["hora"],
                        "egreso": hora,
                        "asistencia_id": ingreso_pendiente.get("asistencia_id") or asistencia_id,
                        "ingreso_marca_id": ingreso_pendiente.get("marca_id"),
                        "ingreso_gps_ok": ingreso_pendiente.get("gps_ok"),
                        "egreso_marca_id": marca_id,
                        "egreso_gps_ok": gps_ok,
                        "error": par_error,
                    }
                )
                ingreso_pendiente = None

        ultima_accion = accion
        ultima_hora = hora

    if ingreso_pendiente:
        pares.append(
            {
                "ingreso": ingreso_pendiente["hora"],
                "egreso": None,
                "asistencia_id": ingreso_pendiente.get("asistencia_id"),
                "ingreso_marca_id": ingreso_pendiente.get("marca_id"),
                "ingreso_gps_ok": ingreso_pendiente.get("gps_ok"),
                "egreso_marca_id": None,
                "egreso_gps_ok": None,
                "error": "Ingreso sin egreso.",
            }
        )
        errores.append("Ingreso sin egreso.")

    # Unifica mensajes repetidos manteniendo orden.
    dedup = []
    seen = set()
    for err in errores:
        if err in seen:
            continue
        seen.add(err)
        dedup.append(err)
    return pares, dedup


def _build_marcas_from_asistencias(asistencias: list[dict]):
    marcas = []
    for asistencia in asistencias or []:
        asistencia_id = asistencia.get("id")
        fecha = _to_date_iso(asistencia.get("fecha"))

        hora_entrada = _to_hhmm(asistencia.get("hora_entrada"))
        if hora_entrada:
            marcas.append(
                {
                    "id": None,
                    "asistencia_id": asistencia_id,
                    "fecha": fecha,
                    "hora": hora_entrada,
                    "accion": "ingreso",
                    "gps_ok": asistencia.get("gps_ok_entrada"),
                }
            )

        hora_salida = _to_hhmm(asistencia.get("hora_salida"))
        if hora_salida:
            marcas.append(
                {
                    "id": None,
                    "asistencia_id": asistencia_id,
                    "fecha": fecha,
                    "hora": hora_salida,
                    "accion": "egreso",
                    "gps_ok": asistencia.get("gps_ok_salida"),
                }
            )
    return marcas


def _sync_simple_marcas_for_asistencia(asistencia_id: int):
    asistencia = get_by_id(asistencia_id)
    if not asistencia:
        return {"synced": False, "reason": "asistencia_not_found"}

    marcas = get_marcas_by_asistencia(asistencia_id)
    non_jornada = [
        m
        for m in marcas
        if str(m.get("tipo_marca") or "").strip().lower() not in {"", "jornada"}
    ]
    if non_jornada:
        return {"synced": False, "reason": "complex_tipo_marca"}

    by_action = {"ingreso": [], "egreso": []}
    for m in marcas:
        accion = str(m.get("accion") or "").strip().lower()
        if accion in by_action:
            by_action[accion].append(m)

    if len(by_action["ingreso"]) > 1 or len(by_action["egreso"]) > 1:
        return {"synced": False, "reason": "multiple_marcas"}

    specs = {
        "ingreso": {
            "hora": _to_hhmm(asistencia.get("hora_entrada")),
            "lat": asistencia.get("lat_entrada"),
            "lon": asistencia.get("lon_entrada"),
            "foto": asistencia.get("foto_entrada"),
            "metodo": asistencia.get("metodo_entrada") or "manual",
            "gps_ok": asistencia.get("gps_ok_entrada"),
            "gps_distancia_m": asistencia.get("gps_distancia_entrada_m"),
            "gps_tolerancia_m": asistencia.get("gps_tolerancia_entrada_m"),
            "gps_ref_lat": asistencia.get("gps_ref_lat_entrada"),
            "gps_ref_lon": asistencia.get("gps_ref_lon_entrada"),
        },
        "egreso": {
            "hora": _to_hhmm(asistencia.get("hora_salida")),
            "lat": asistencia.get("lat_salida"),
            "lon": asistencia.get("lon_salida"),
            "foto": asistencia.get("foto_salida"),
            "metodo": asistencia.get("metodo_salida") or "manual",
            "gps_ok": asistencia.get("gps_ok_salida"),
            "gps_distancia_m": asistencia.get("gps_distancia_salida_m"),
            "gps_tolerancia_m": asistencia.get("gps_tolerancia_salida_m"),
            "gps_ref_lat": asistencia.get("gps_ref_lat_salida"),
            "gps_ref_lon": asistencia.get("gps_ref_lon_salida"),
        },
    }

    created = 0
    deleted = 0
    for accion in ("ingreso", "egreso"):
        existing = by_action[accion][0] if by_action[accion] else None
        if existing:
            delete_marca_by_id(int(existing["id"]))
            deleted += 1

        spec = specs[accion]
        if not spec["hora"]:
            continue

        create_marca(
            empresa_id=int(asistencia["empresa_id"]),
            empleado_id=int(asistencia["empleado_id"]),
            asistencia_id=int(asistencia_id),
            fecha=_to_date_iso(asistencia.get("fecha")),
            hora=spec["hora"],
            accion=accion,
            metodo=spec["metodo"],
            tipo_marca="jornada",
            lat=spec["lat"],
            lon=spec["lon"],
            foto=spec["foto"],
            gps_ok=spec["gps_ok"],
            gps_distancia_m=spec["gps_distancia_m"],
            gps_tolerancia_m=spec["gps_tolerancia_m"],
            gps_ref_lat=spec["gps_ref_lat"],
            gps_ref_lon=spec["gps_ref_lon"],
            estado=asistencia.get("estado"),
            observaciones=asistencia.get("observaciones"),
        )
        created += 1

    return {"synced": True, "created": created, "deleted": deleted}


def _resolve_planilla_filters(args):
    today = datetime.date.today().isoformat()
    empresa_id = args.get("empresa_id", type=int)
    sucursal_id = args.get("sucursal_id", type=int)
    fecha_raw = args.get("fecha") or today
    error = (args.get("error") or "").strip() or None
    msg = (args.get("msg") or "").strip() or None
    try:
        fecha = _parse_date_iso(fecha_raw) or today
    except ValueError:
        fecha = today
        if not error:
            error = "Fecha invalida. Use formato YYYY-MM-DD."
    return {
        "today": today,
        "empresa_id": empresa_id,
        "sucursal_id": sucursal_id,
        "fecha": fecha,
        "error": error,
        "msg": msg,
    }


def _planilla_redirect(*, empresa_id: int | None, sucursal_id: int | None, fecha: str, error: str | None = None, msg: str | None = None):
    params = {"fecha": fecha}
    if empresa_id:
        params["empresa_id"] = empresa_id
    if sucursal_id:
        params["sucursal_id"] = sucursal_id
    if error:
        params["error"] = error
    if msg:
        params["msg"] = msg
    return redirect(url_for("asistencias.planilla", **params))


def _marca_for_form(marca: dict):
    data = dict(marca or {})
    data["hora"] = _to_hhmm(data.get("hora"))
    data["fecha"] = _to_date_iso(data.get("fecha"))
    return data


def _build_planilla_context(*, empresa_id: int | None, sucursal_id: int | None, fecha: str):
    empresas = get_empresas(include_inactive=True)
    all_sucursales = get_sucursales(include_inactive=True)
    sucursales = [s for s in all_sucursales if not empresa_id or s.get("empresa_id") == empresa_id]

    config_empresa = get_configuracion_empresa_by_id(empresa_id) if empresa_id else None
    intervalo_minimo_fichadas = _get_intervalo_minimo_fichadas_min(config_empresa)

    empleados = get_empleados(include_inactive=True)
    empleados_by_id = {e.get("id"): e for e in empleados}
    empleados_filtrados = []
    for e in empleados:
        if empresa_id and e.get("empresa_id") != empresa_id:
            continue
        if sucursal_id and e.get("sucursal_id") != sucursal_id:
            continue
        empleados_filtrados.append(e)

    marcas = get_marcas_admin_export(
        empresa_id=empresa_id,
        fecha_desde=fecha,
        fecha_hasta=fecha,
        limit=20000,
    )
    asistencias_rows, _ = get_page(1, 20000, None, fecha, fecha, None)

    marcas_por_empleado = {}
    for m in marcas:
        if sucursal_id:
            emp_info = empleados_by_id.get(m.get("empleado_id"))
            if not emp_info or emp_info.get("sucursal_id") != sucursal_id:
                continue
        marcas_por_empleado.setdefault(m.get("empleado_id"), []).append(m)

    asistencias_por_empleado = {}
    for a in asistencias_rows:
        empleado_id = a.get("empleado_id")
        if not empleado_id:
            continue
        if not _to_hhmm(a.get("hora_entrada")) and not _to_hhmm(a.get("hora_salida")):
            continue
        emp_info = empleados_by_id.get(empleado_id)
        if not emp_info:
            continue
        if empresa_id and emp_info.get("empresa_id") != empresa_id:
            continue
        if sucursal_id and emp_info.get("sucursal_id") != sucursal_id:
            continue
        asistencias_por_empleado.setdefault(empleado_id, []).append(a)

    # Si no filtran empresa, evita una planilla gigante: mostrar solo quienes tuvieron marcas ese dia.
    if not empresa_id:
        ids_con_marca = {emp_id for emp_id in marcas_por_empleado.keys() if emp_id}
        ids_con_asistencia = {emp_id for emp_id in asistencias_por_empleado.keys() if emp_id}
        ids_visibles = ids_con_marca | ids_con_asistencia
        empleados_filtrados = [e for e in empleados_filtrados if e.get("id") in ids_visibles]

    planilla_rows = []
    max_pares = 3
    for e in empleados_filtrados:
        emp_marcas = marcas_por_empleado.get(e["id"], [])
        if emp_marcas:
            source_marcas = emp_marcas
        else:
            source_marcas = _build_marcas_from_asistencias(asistencias_por_empleado.get(e["id"], []))

        emp_marcas = sorted(
            source_marcas,
            key=lambda row: (_to_hhmm(row.get("hora")) or "", row.get("id") or 0),
        )
        pares, errores = _build_planilla_pares(emp_marcas, intervalo_minimo_fichadas)
        max_pares = max(max_pares, len(pares))

        asistencia_ids = []
        seen_ids = set()
        for par in pares:
            asistencia_id = par.get("asistencia_id")
            if asistencia_id and asistencia_id not in seen_ids:
                seen_ids.add(asistencia_id)
                asistencia_ids.append(asistencia_id)

        planilla_rows.append(
            {
                "empleado_id": e["id"],
                "apellido": e.get("apellido"),
                "nombre": e.get("nombre"),
                "dni": e.get("dni"),
                "pares": pares,
                "errores": errores,
                "asistencia_ids": asistencia_ids,
                "asistencia_base_id": asistencia_ids[0] if asistencia_ids else None,
            }
        )

    planilla_rows.sort(key=lambda r: ((r.get("apellido") or "").lower(), (r.get("nombre") or "").lower()))
    empresa_sel = next((emp for emp in empresas if emp.get("id") == empresa_id), None)
    sucursal_sel = next((s for s in sucursales if s.get("id") == sucursal_id), None)
    return {
        "empresas": empresas,
        "sucursales": sucursales,
        "empresa_sel": empresa_sel,
        "sucursal_sel": sucursal_sel,
        "planilla_rows": planilla_rows,
        "max_pares": max_pares,
        "intervalo_minimo_fichadas": intervalo_minimo_fichadas,
    }


def _extract_form_data(form):
    return {
        "empleado_id": int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None,
        "fecha": (form.get("fecha") or "").strip(),
        "hora_entrada": (form.get("hora_entrada") or "").strip(),
        "hora_salida": (form.get("hora_salida") or "").strip(),
        "lat_entrada": _parse_float(form.get("lat_entrada")),
        "lon_entrada": _parse_float(form.get("lon_entrada")),
        "lat_salida": _parse_float(form.get("lat_salida")),
        "lon_salida": _parse_float(form.get("lon_salida")),
        "foto_entrada": (form.get("foto_entrada") or "").strip(),
        "foto_salida": (form.get("foto_salida") or "").strip(),
        "metodo_entrada": (form.get("metodo_entrada") or "").strip(),
        "metodo_salida": (form.get("metodo_salida") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip(),
    }


def _validate(form):
    errors = []
    if not (form.get("empleado_id") or "").isdigit():
        errors.append("Empleado es requerido.")
    if not (form.get("fecha") or "").strip():
        errors.append("Fecha es requerida.")

    for field, label, min_v, max_v in [
        ("lat_entrada", "Lat entrada", -90, 90),
        ("lat_salida", "Lat salida", -90, 90),
        ("lon_entrada", "Lon entrada", -180, 180),
        ("lon_salida", "Lon salida", -180, 180),
    ]:
        value = (form.get(field) or "").strip()
        if value:
            try:
                v = float(value)
            except ValueError:
                errors.append(f"{label} invalida.")
                continue
            if v < min_v or v > max_v:
                errors.append(f"{label} fuera de rango.")

    for field, label in [
        ("metodo_entrada", "Metodo entrada"),
        ("metodo_salida", "Metodo salida"),
    ]:
        value = (form.get(field) or "").strip()
        if value and value not in {"qr", "manual", "facial"}:
            errors.append(f"{label} invalido.")

    empleado_id = int(form.get("empleado_id")) if (form.get("empleado_id") or "").isdigit() else None
    fecha = (form.get("fecha") or "").strip()
    hora_entrada = (form.get("hora_entrada") or "").strip()
    hora_salida = (form.get("hora_salida") or "").strip()
    extra_errors, _ = validar_asistencia(empleado_id, fecha, hora_entrada, hora_salida)
    errors.extend(extra_errors)
    return errors


@asistencias_bp.route("/")
@role_required("admin", "rrhh", "supervisor")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    search = request.args.get("q")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    error = (request.args.get("error") or "").strip() or None
    asistencias, total = get_page(page, per_page, empleado_id, fecha_desde, fecha_hasta, search)
    empleados = get_empleados(include_inactive=True)
    return render_template(
        "asistencias/listado.html",
        asistencias=asistencias,
        empleados=empleados,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        q=search,
        error=error,
        page=page,
        per_page=per_page,
        total=total,
        today=datetime.date.today().isoformat(),
    )


@asistencias_bp.route("/planilla")
@role_required("admin", "rrhh", "supervisor")
def planilla():
    filters = _resolve_planilla_filters(request.args)
    context = _build_planilla_context(
        empresa_id=filters["empresa_id"],
        sucursal_id=filters["sucursal_id"],
        fecha=filters["fecha"],
    )
    return render_template(
        "asistencias/planilla.html",
        empresa_id=filters["empresa_id"],
        sucursal_id=filters["sucursal_id"],
        fecha=filters["fecha"],
        today=filters["today"],
        error=filters["error"],
        msg=filters["msg"],
        **context,
    )


@asistencias_bp.route("/planilla.xls")
@role_required("admin", "rrhh", "supervisor")
def planilla_xls():
    filters = _resolve_planilla_filters(request.args)
    context = _build_planilla_context(
        empresa_id=filters["empresa_id"],
        sucursal_id=filters["sucursal_id"],
        fecha=filters["fecha"],
    )
    html = render_template(
        "asistencias/planilla_xls.html",
        empresa_id=filters["empresa_id"],
        sucursal_id=filters["sucursal_id"],
        fecha=filters["fecha"],
        **context,
    )
    filename = f"planilla_fichadas_{filters['fecha']}.xls"
    content = "\ufeff" + html
    return Response(
        content,
        mimetype="application/vnd.ms-excel; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@asistencias_bp.route("/planilla.pdf")
@role_required("admin", "rrhh", "supervisor")
def planilla_pdf():
    filters = _resolve_planilla_filters(request.args)
    context = _build_planilla_context(
        empresa_id=filters["empresa_id"],
        sucursal_id=filters["sucursal_id"],
        fecha=filters["fecha"],
    )
    auto_print = (request.args.get("auto_print") or "").strip() == "1"
    return render_template(
        "asistencias/planilla_pdf.html",
        empresa_id=filters["empresa_id"],
        sucursal_id=filters["sucursal_id"],
        fecha=filters["fecha"],
        auto_print=auto_print,
        **context,
    )


@asistencias_bp.route("/planilla/marca/editar/<int:marca_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh", "supervisor")
def planilla_marca_editar(marca_id):
    marca = get_marca_by_id(marca_id)
    if not marca:
        return _planilla_redirect(
            empresa_id=request.args.get("empresa_id", type=int),
            sucursal_id=request.args.get("sucursal_id", type=int),
            fecha=(request.args.get("fecha") or datetime.date.today().isoformat()),
            error="Marca no encontrada.",
        )

    empresa_id = request.values.get("empresa_id", type=int)
    sucursal_id = request.values.get("sucursal_id", type=int)
    fecha = (request.values.get("fecha") or _to_date_iso(marca.get("fecha")) or datetime.date.today().isoformat()).strip()

    if request.method == "POST":
        hora_raw = request.form.get("hora")
        accion = (request.form.get("accion") or "").strip().lower()
        observaciones = (request.form.get("observaciones") or "").strip() or None
        try:
            hora = _parse_hhmm(hora_raw)
            if accion not in {"ingreso", "egreso"}:
                raise ValueError("Accion invalida.")
        except ValueError as exc:
            return render_template(
                "asistencias/planilla_marca_form.html",
                mode="edit",
                marca=_marca_for_form({**marca, "hora": hora_raw, "accion": accion, "observaciones": observaciones}),
                empresa_id=empresa_id,
                sucursal_id=sucursal_id,
                fecha=fecha,
                error=str(exc),
            )

        update_marca_basic(marca_id, hora=hora, accion=accion, observaciones=observaciones)
        if marca.get("asistencia_id"):
            sync_from_asistencia_marcas(int(marca["asistencia_id"]))
        log_audit(session, "update", "asistencia_marcas", marca_id)
        return _planilla_redirect(
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha=fecha,
            msg=f"Marca #{marca_id} actualizada.",
        )

    return render_template(
        "asistencias/planilla_marca_form.html",
        mode="edit",
        marca=_marca_for_form(marca),
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha,
        error=None,
    )


@asistencias_bp.route("/planilla/marca/eliminar/<int:marca_id>", methods=["POST"])
@role_required("admin", "rrhh", "supervisor")
def planilla_marca_eliminar(marca_id):
    empresa_id = request.form.get("empresa_id", type=int)
    sucursal_id = request.form.get("sucursal_id", type=int)
    fecha = (request.form.get("fecha") or datetime.date.today().isoformat()).strip()

    marca = get_marca_by_id(marca_id)
    if not marca:
        return _planilla_redirect(
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha=fecha,
            error="Marca no encontrada.",
        )

    asistencia_id = marca.get("asistencia_id")
    delete_marca_by_id(marca_id)
    if asistencia_id:
        sync_from_asistencia_marcas(int(asistencia_id))
    log_audit(session, "delete", "asistencia_marcas", marca_id)
    return _planilla_redirect(
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha,
        msg=f"Marca #{marca_id} eliminada.",
    )


@asistencias_bp.route("/planilla/marca/agregar", methods=["GET", "POST"])
@role_required("admin", "rrhh", "supervisor")
def planilla_marca_agregar():
    asistencia_id = request.values.get("asistencia_id", type=int)
    empresa_id = request.values.get("empresa_id", type=int)
    sucursal_id = request.values.get("sucursal_id", type=int)
    fecha = (request.values.get("fecha") or datetime.date.today().isoformat()).strip()
    accion = (request.values.get("accion") or "").strip().lower()

    if not asistencia_id:
        return _planilla_redirect(
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha=fecha,
            error="Debe indicar una asistencia para agregar la marca.",
        )

    asistencia = get_by_id(asistencia_id)
    if not asistencia:
        return _planilla_redirect(
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha=fecha,
            error="Asistencia no encontrada.",
        )
    if accion not in {"ingreso", "egreso"}:
        accion = "egreso"

    if request.method == "POST":
        hora_raw = request.form.get("hora")
        observaciones = (request.form.get("observaciones") or "").strip() or None
        try:
            hora = _parse_hhmm(hora_raw)
        except ValueError as exc:
            return render_template(
                "asistencias/planilla_marca_form.html",
                mode="new",
                marca=_marca_for_form({
                    "asistencia_id": asistencia_id,
                    "fecha": asistencia.get("fecha"),
                    "accion": accion,
                    "hora": hora_raw,
                    "observaciones": observaciones,
                }),
                empresa_id=empresa_id,
                sucursal_id=sucursal_id,
                fecha=fecha,
                error=str(exc),
            )

        if accion == "ingreso":
            lat = asistencia.get("lat_entrada")
            lon = asistencia.get("lon_entrada")
            foto = asistencia.get("foto_entrada")
            metodo = asistencia.get("metodo_entrada") or "manual"
            gps_ok = asistencia.get("gps_ok_entrada")
            gps_distancia_m = asistencia.get("gps_distancia_entrada_m")
            gps_tolerancia_m = asistencia.get("gps_tolerancia_entrada_m")
            gps_ref_lat = asistencia.get("gps_ref_lat_entrada")
            gps_ref_lon = asistencia.get("gps_ref_lon_entrada")
        else:
            lat = asistencia.get("lat_salida")
            lon = asistencia.get("lon_salida")
            foto = asistencia.get("foto_salida")
            metodo = asistencia.get("metodo_salida") or "manual"
            gps_ok = asistencia.get("gps_ok_salida")
            gps_distancia_m = asistencia.get("gps_distancia_salida_m")
            gps_tolerancia_m = asistencia.get("gps_tolerancia_salida_m")
            gps_ref_lat = asistencia.get("gps_ref_lat_salida")
            gps_ref_lon = asistencia.get("gps_ref_lon_salida")

        marca_id = create_marca(
            empresa_id=int(asistencia["empresa_id"]),
            empleado_id=int(asistencia["empleado_id"]),
            asistencia_id=int(asistencia_id),
            fecha=_to_date_iso(asistencia.get("fecha")) or fecha,
            hora=hora,
            accion=accion,
            metodo=metodo,
            tipo_marca="jornada",
            lat=lat,
            lon=lon,
            foto=foto,
            gps_ok=gps_ok,
            gps_distancia_m=gps_distancia_m,
            gps_tolerancia_m=gps_tolerancia_m,
            gps_ref_lat=gps_ref_lat,
            gps_ref_lon=gps_ref_lon,
            estado=asistencia.get("estado"),
            observaciones=observaciones,
        )
        sync_from_asistencia_marcas(int(asistencia_id))
        log_audit(session, "create", "asistencia_marcas", marca_id)
        return _planilla_redirect(
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha=fecha,
            msg=f"Marca #{marca_id} agregada.",
        )

    return render_template(
        "asistencias/planilla_marca_form.html",
        mode="new",
        marca=_marca_for_form({
            "asistencia_id": asistencia_id,
            "fecha": asistencia.get("fecha"),
            "accion": accion,
            "hora": "",
            "observaciones": "",
        }),
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha,
        error=None,
    )


@asistencias_bp.route("/marcas")
@role_required("admin", "rrhh", "supervisor")
def marcas():
    page = request.args.get("page", 1, type=int) or 1
    page = max(1, page)
    per_page = request.args.get("per", 20, type=int) or 20
    per_page = max(1, min(per_page, 100))

    empresa_id = request.args.get("empresa_id", type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    q = (request.args.get("q") or "").strip()
    tipo_marca = (request.args.get("tipo_marca") or "").strip() or None
    accion = (request.args.get("accion") or "").strip() or None
    metodo = (request.args.get("metodo") or "").strip() or None
    gps_ok = request.args.get("gps_ok", type=int)
    backfill_ingresos = request.args.get("backfill_ingresos", type=int)
    backfill_egresos = request.args.get("backfill_egresos", type=int)

    error = None
    try:
        fecha_desde = _parse_date_iso(request.args.get("fecha_desde"))
        fecha_hasta = _parse_date_iso(request.args.get("fecha_hasta"))
    except ValueError:
        fecha_desde = None
        fecha_hasta = None
        error = "Rango de fechas invalido. Use formato YYYY-MM-DD."

    rows, total = get_marcas_admin_page(
        page=page,
        per_page=per_page,
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo_marca=tipo_marca,
        accion=accion,
        metodo=metodo,
        search=q or None,
        gps_ok=gps_ok if gps_ok in (0, 1) else None,
    )

    return render_template(
        "asistencias/marcas.html",
        marcas=rows,
        total=total,
        page=page,
        per_page=per_page,
        empresas=get_empresas(include_inactive=True),
        empleados=get_empleados(include_inactive=True),
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde or "",
        fecha_hasta=fecha_hasta or "",
        tipo_marca=tipo_marca or "",
        accion=accion or "",
        metodo=metodo or "",
        gps_ok=gps_ok if gps_ok in (0, 1) else "",
        q=q,
        error=error,
        backfill_ingresos=backfill_ingresos,
        backfill_egresos=backfill_egresos,
    )


@asistencias_bp.route("/marcas.csv")
@role_required("admin", "rrhh", "supervisor")
def marcas_csv():
    empresa_id = request.args.get("empresa_id", type=int)
    empleado_id = request.args.get("empleado_id", type=int)
    q = (request.args.get("q") or "").strip()
    tipo_marca = (request.args.get("tipo_marca") or "").strip() or None
    accion = (request.args.get("accion") or "").strip() or None
    metodo = (request.args.get("metodo") or "").strip() or None
    gps_ok = request.args.get("gps_ok", type=int)

    try:
        fecha_desde = _parse_date_iso(request.args.get("fecha_desde"))
        fecha_hasta = _parse_date_iso(request.args.get("fecha_hasta"))
    except ValueError:
        return redirect(url_for("asistencias.marcas"))

    rows = get_marcas_admin_export(
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo_marca=tipo_marca,
        accion=accion,
        metodo=metodo,
        search=q or None,
        gps_ok=gps_ok if gps_ok in (0, 1) else None,
        limit=10000,
    )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "id",
            "empresa",
            "empleado",
            "dni",
            "fecha",
            "hora",
            "accion",
            "tipo_marca",
            "metodo",
            "gps_ok",
            "gps_distancia_m",
            "gps_tolerancia_m",
            "lat",
            "lon",
            "estado",
            "observaciones",
            "fecha_creacion",
        ]
    )

    for r in rows:
        writer.writerow(
            [
                r.get("id"),
                r.get("empresa_nombre"),
                f"{r.get('apellido') or ''} {r.get('nombre') or ''}".strip(),
                r.get("dni"),
                r.get("fecha"),
                r.get("hora"),
                r.get("accion"),
                r.get("tipo_marca"),
                r.get("metodo"),
                r.get("gps_ok"),
                r.get("gps_distancia_m"),
                r.get("gps_tolerancia_m"),
                r.get("lat"),
                r.get("lon"),
                r.get("estado"),
                r.get("observaciones"),
                r.get("fecha_creacion"),
            ]
        )

    csv_content = "\ufeff" + out.getvalue()
    filename = f"historial_marcas_{datetime.date.today().isoformat()}.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@asistencias_bp.route("/marcas/backfill", methods=["POST"])
@role_required("admin")
def marcas_backfill():
    inserted_ingresos, inserted_egresos = backfill_marcas()

    return redirect(
        url_for(
            "asistencias.marcas",
            page=_parse_int(request.form.get("page")) or 1,
            per=_parse_int(request.form.get("per")) or 20,
            empresa_id=request.form.get("empresa_id") or "",
            empleado_id=request.form.get("empleado_id") or "",
            fecha_desde=request.form.get("fecha_desde") or "",
            fecha_hasta=request.form.get("fecha_hasta") or "",
            tipo_marca=request.form.get("tipo_marca") or "",
            accion=request.form.get("accion") or "",
            metodo=request.form.get("metodo") or "",
            gps_ok=request.form.get("gps_ok") or "",
            q=request.form.get("q") or "",
            backfill_ingresos=inserted_ingresos,
            backfill_egresos=inserted_egresos,
        )
    )


@asistencias_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh", "supervisor")
def nuevo():
    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract_form_data(request.form)
        if errors:
            return render_template("asistencias/form.html", mode="new", data=data, errors=errors, empleados=empleados)

        _, estado_calc = validar_asistencia(
            data.get("empleado_id"),
            data.get("fecha"),
            data.get("hora_entrada"),
            data.get("hora_salida"),
        )
        data["estado"] = estado_calc or ("ausente" if not data.get("hora_entrada") and not data.get("hora_salida") else "ok")

        asistencia_id = create(data)
        log_audit(session, "create", "asistencias", asistencia_id)
        sync_result = _sync_simple_marcas_for_asistencia(int(asistencia_id))
        if not sync_result.get("synced"):
            current_app.logger.warning(
                "asistencias_nuevo_sync_marcas_skipped",
                extra={"extra": {"asistencia_id": int(asistencia_id), "reason": sync_result.get("reason")}},
            )
        return redirect(url_for("asistencias.listado"))

    return render_template("asistencias/form.html", mode="new", data={}, empleados=empleados)


@asistencias_bp.route("/generar-ausentes", methods=["POST"])
@role_required("admin", "rrhh", "supervisor")
def generar_ausentes_post():
    modo = (request.form.get("modo") or "").strip().lower()
    fecha = (request.form.get("fecha") or "").strip()
    fecha_desde = (request.form.get("fecha_desde") or "").strip()
    fecha_hasta = (request.form.get("fecha_hasta") or "").strip()
    hoy = datetime.date.today()
    hoy_iso = hoy.isoformat()

    if modo == "rango":
        if not (fecha_desde and fecha_hasta):
            return redirect(url_for("asistencias.listado"))
        try:
            desde_dt = datetime.date.fromisoformat(fecha_desde)
            hasta_dt = datetime.date.fromisoformat(fecha_hasta)
        except ValueError:
            return redirect(url_for("asistencias.listado", error="Rango de fechas invalido. Use formato YYYY-MM-DD."))

        if desde_dt > hoy:
            return redirect(url_for("asistencias.listado", error=f"fecha_desde no puede ser mayor a hoy ({hoy_iso})."))
        if hasta_dt > hoy:
            return redirect(url_for("asistencias.listado", error=f"fecha_hasta no puede ser mayor a hoy ({hoy_iso})."))

        _, errors = generar_ausentes_rango(fecha_desde, fecha_hasta)
        if errors:
            return redirect(
                url_for(
                    "asistencias.listado",
                    error=errors[0],
                    fecha_desde=fecha_desde,
                    fecha_hasta=fecha_hasta,
                )
            )
        return redirect(
            url_for(
                "asistencias.listado",
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        )

    if modo and modo != "dia":
        return redirect(url_for("asistencias.listado"))

    if not fecha:
        return redirect(url_for("asistencias.listado"))
    try:
        fecha_dt = datetime.date.fromisoformat(fecha)
    except ValueError:
        return redirect(url_for("asistencias.listado", error="Fecha invalida."))

    if fecha_dt > hoy:
        return redirect(url_for("asistencias.listado", error=f"fecha no puede ser mayor a hoy ({hoy_iso})."))

    _, errors = generar_ausentes(fecha)
    if errors:
        return redirect(url_for("asistencias.listado", error=errors[0], fecha_desde=fecha, fecha_hasta=fecha))
    return redirect(url_for("asistencias.listado", fecha_desde=fecha, fecha_hasta=fecha))


@asistencias_bp.route("/editar/<int:asistencia_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh", "supervisor")
def editar(asistencia_id):
    asistencia = get_by_id(asistencia_id)
    if not asistencia:
        abort(404)

    empleados = get_empleados(include_inactive=True)
    if request.method == "POST":
        errors = _validate(request.form)
        data = _extract_form_data(request.form)
        if errors:
            merged = dict(asistencia)
            merged.update(data)
            return render_template("asistencias/form.html", mode="edit", data=merged, errors=errors, empleados=empleados)

        _, estado_calc = validar_asistencia(
            data.get("empleado_id"),
            data.get("fecha"),
            data.get("hora_entrada"),
            data.get("hora_salida"),
        )
        data["estado"] = estado_calc or ("ausente" if not data.get("hora_entrada") and not data.get("hora_salida") else "ok")

        update(asistencia_id, data)
        log_audit(session, "update", "asistencias", asistencia_id)
        sync_result = _sync_simple_marcas_for_asistencia(int(asistencia_id))
        if not sync_result.get("synced"):
            current_app.logger.warning(
                "asistencias_editar_sync_marcas_skipped",
                extra={"extra": {"asistencia_id": int(asistencia_id), "reason": sync_result.get("reason")}},
            )
        return redirect(url_for("asistencias.listado"))

    return render_template("asistencias/form.html", mode="edit", data=asistencia, empleados=empleados)


@asistencias_bp.route("/eliminar/<int:asistencia_id>", methods=["POST"])
@role_required("admin", "rrhh", "supervisor")
def eliminar(asistencia_id):
    delete(asistencia_id)
    log_audit(session, "delete", "asistencias", asistencia_id)
    return redirect(url_for("asistencias.listado"))


@asistencias_bp.route("/horario-esperado")
@role_required("admin", "rrhh", "supervisor")
def horario_esperado():
    empleado_id = request.args.get("empleado_id", type=int)
    fecha = (request.args.get("fecha") or "").strip()
    if not empleado_id or not fecha:
        return jsonify({"error": "empleado_id y fecha son requeridos"}), 400
    try:
        data = get_horario_esperado(empleado_id, fecha)
    except ValueError:
        return jsonify({"error": "fecha invalida"}), 400
    if not data:
        return jsonify({"error": "sin horario esperado"}), 404
    return jsonify(data)
