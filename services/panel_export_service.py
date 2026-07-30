from __future__ import annotations

import datetime
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from flask import abort, current_app, redirect, request, session, url_for

from repositories.auditoria_repository import get_page as get_auditoria_page
from repositories.calificacion_app_repository import get_calificaciones_page
from repositories.empleado_excepcion_repository import get_all as get_excepciones
from repositories.empleado_horario_repository import get_historial as get_empleado_horario_historial
from repositories.empleado_repository import get_all as get_empleados
from repositories.empleado_repository import get_page_for_roles
from repositories.empresa_repository import get_all as get_empresas
from repositories.feedback_cliente_repository import get_page as get_clientes_page
from repositories.feedback_motivo_repository import get_page as get_motivos_page
from repositories.feedback_repository import get_page as get_feedbacks_page
from repositories.franco_repository import get_all as get_francos
from repositories.justificacion_repository import get_page as get_justificaciones_page
from repositories.legajo_evento_repository import get_eventos_page, get_tipos_evento_page
from repositories.localidad_repository import get_all as get_localidades
from repositories.mobile_sesiones_repository import get_sesiones_page
from repositories.organigrama_repository import get_organigrama
from repositories.pedido_mercaderia_repository import get_export as get_pedidos_export
from repositories.qr_puerta_repository import get_recent as get_qr_historial_recent
from repositories.premio_concurso_repository import get_concursos_page
from repositories.puesto_repository import get_page as get_puestos_page
from repositories.rol_repository import get_page as get_roles_page
from repositories.sector_repository import get_page as get_sectores_page
from repositories.sector_repository import get_all as get_sectores
from repositories.sucursal_repository import get_all as get_sucursales
from repositories.usuarios_app_repository import get_page as get_usuarios_page
from repositories.vacacion_repository import get_all as get_vacaciones
from repositories.vacaciones_repository import get_movimientos_export
from repositories.app_version_repository import get_all as get_app_versions
from repositories.configuracion_empresa_repository import get_all as get_configuraciones_empresa
from repositories.horario_repository import get_all as get_horarios
from repositories.asistencia_repository import get_page as get_asistencias_page
from repositories.adelanto_repository import get_export as get_adelantos_export
from repositories.trivia_repository import get_trivias_page
from repositories.skap_repository import get_evaluaciones_page, get_planes_page
from repositories.kpi_sectorial_repository import get_kpis_by_sector
from services.horario_service import get_horarios_resumen
from services.table_export_service import build_attachment_response, build_table_export, normalize_export_format
from web.vacaciones.vacaciones_routes import _extract_filters as vacaciones_extract_filters
from web.premios_concursos.premios_concursos_routes import _extract_concurso_filters as concursos_extract_filters
import web.auth.decorators as auth_decorators


EXPORT_PAGE_SIZE = 1_000_000


@dataclass(frozen=True)
class ExportSpec:
    title: str
    filename_base: str
    loader: Callable[[], list[dict[str, Any]]]
    toolbar_enabled: Callable[[], bool] = lambda: True
    disabled_message: str = "Seleccione filtros validos para exportar."


def _int_arg(name: str) -> int | None:
    return request.args.get(name, type=int)


def _int_arg_or_none(name: str) -> int | None:
    value = request.args.get(name, type=int)
    return value if value not in {None, 0} else None


def _str_arg(name: str) -> str | None:
    return (request.args.get(name) or "").strip() or None


def _tristate_arg(name: str) -> int | None:
    raw = str(request.args.get(name) or "all").strip().lower()
    if raw == "1":
        return 1
    if raw == "0":
        return 0
    return None


def _page_rows(getter: Callable[..., tuple[list[dict[str, Any]], int]], *args, **kwargs) -> list[dict[str, Any]]:
    rows, _ = getter(1, EXPORT_PAGE_SIZE, *args, **kwargs)
    return list(rows or [])


def _all_rows(getter: Callable[..., list[dict[str, Any]]], *args, **kwargs) -> list[dict[str, Any]]:
    return list(getter(*args, **kwargs) or [])


def _parse_active_raw(value: Any) -> tuple[int | None, str]:
    raw = str(value or "all").strip().lower()
    if raw == "1":
        return 1, "1"
    if raw == "0":
        return 0, "0"
    return None, "all"


def _parse_legajo_evento_estado() -> str | None:
    raw = str(request.args.get("estado") or "all").strip().lower()
    if raw in {"all", "vigente", "anulado"}:
        return None if raw == "all" else raw
    return None


def _vacaciones_filters() -> dict[str, Any]:
    filters, _ = vacaciones_extract_filters(request.args)
    return filters


def _concursos_filters() -> dict[str, Any]:
    filters, _ = concursos_extract_filters(request.args)
    return filters


def _load_vacaciones_export() -> list[dict[str, Any]]:
    filters = _vacaciones_filters()
    return _all_rows(
        get_movimientos_export,
        empleado_id=filters["empleado_id"],
        sector_id=filters["sector_id"],
        search=filters["search"],
        estado=filters["estado"],
        tipo=filters["tipo"],
        anio=filters["anio"],
        mes=filters["mes"],
        limit=EXPORT_PAGE_SIZE,
    )


def _load_concursos_export() -> list[dict[str, Any]]:
    filters = _concursos_filters()
    return _page_rows(
        get_concursos_page,
        filters["empresa_id"],
        filters["sector_id"],
        filters["search"],
        filters["activo"],
        filters["alcance"],
    )


def _load_kpis_export() -> list[dict[str, Any]]:
    sector_id = _int_arg("sector_id")
    if not sector_id:
        return []
    return _all_rows(get_kpis_by_sector, sector_id)


def _load_feedback_registros_export() -> list[dict[str, Any]]:
    estado = _str_arg("estado")
    if estado not in {None, "pendiente", "en_proceso", "resuelto", "vencido"}:
        estado = None
    return _page_rows(
        get_feedbacks_page,
        estado=estado,
        search=_str_arg("q"),
        sector_id=_int_arg("sector_id"),
        sucursal_id=_int_arg("sucursal_id"),
        empleado_activo=_tristate_arg("empleado_activo"),
    )


def _flatten_organigrama() -> list[dict[str, Any]]:
    empresa_id = _int_arg("empresa_id")
    activo, activo_raw = _parse_active_raw(request.args.get("activo"))
    empleado_activo, empleado_activo_raw = _parse_active_raw(request.args.get("empleado_activo"))
    organigramas = get_organigrama(
        empresa_id=empresa_id,
        activo=activo,
        empleado_activo=empleado_activo,
    )

    rows: list[dict[str, Any]] = []

    def _employee_rows(employee: dict[str, Any], *, company_name: str, sector_name: str, sector_id: int, level: int, manager_name: str | None = None):
        rows.append(
            {
                "tipo": "empleado",
                "empresa_nombre": company_name,
                "sector_id": sector_id,
                "sector_nombre": sector_name,
                "nivel": level,
                "empleado_id": employee.get("id"),
                "empleado_nombre": employee.get("nombre_completo") or f"{employee.get('apellido') or ''} {employee.get('nombre') or ''}".strip(),
                "empleado_activo": employee.get("activo"),
                "empleado_puesto": employee.get("puesto_nombre"),
                "reporta_a": manager_name or "",
                "email": employee.get("email"),
                "asignacion_adicional": employee.get("asignacion_adicional"),
                "puestos_adicionales": len(employee.get("puestos_adicionales") or []),
            }
        )
        for subordinate in employee.get("subordinados") or []:
            _employee_rows(
                subordinate,
                company_name=company_name,
                sector_name=sector_name,
                sector_id=sector_id,
                level=level + 1,
                manager_name=employee.get("nombre_completo"),
            )

    def _sector_rows(node: dict[str, Any], *, company_name: str, level: int):
        rows.append(
            {
                "tipo": "sector",
                "empresa_nombre": company_name,
                "sector_id": node.get("id"),
                "sector_nombre": node.get("nombre"),
                "nivel": level,
                "sector_activo": node.get("activo"),
                "sector_padre_nombre": node.get("sector_padre_nombre"),
                "responsable_nombre": node.get("responsable_nombre_completo") or "",
                "responsable_email": node.get("responsable_email") or "",
                "responsable_puesto": node.get("responsable_puesto_nombre") or "",
                "dotacion_directa": node.get("dotacion_directa") or 0,
                "dotacion_total": node.get("dotacion_total") or 0,
                "puestos_resumen": ", ".join(
                    f"{item.get('nombre')} ({item.get('count')})"
                    for item in (node.get("puestos_resumen") or [])
                ),
            }
        )

        for employee in node.get("empleados_tree") or []:
            _employee_rows(
                employee,
                company_name=company_name,
                sector_name=node.get("nombre") or "",
                sector_id=int(node.get("id") or 0),
                level=level,
            )

        for child in node.get("children") or []:
            _sector_rows(child, company_name=company_name, level=level + 1)

    for company in organigramas:
        company_name = company.get("empresa_nombre") or ""
        for root in company.get("roots") or []:
            _sector_rows(root, company_name=company_name, level=1)
        for employee in company.get("empleados_sin_sector") or []:
            rows.append(
                {
                    "tipo": "empleado_sin_sector",
                    "empresa_nombre": company_name,
                    "sector_id": "",
                    "sector_nombre": "",
                    "nivel": 0,
                    "empleado_id": employee.get("id"),
                    "empleado_nombre": employee.get("nombre_completo") or f"{employee.get('apellido') or ''} {employee.get('nombre') or ''}".strip(),
                    "empleado_activo": employee.get("activo"),
                    "empleado_puesto": employee.get("puesto_nombre"),
                    "reporta_a": employee.get("reporta_a_empleado_id") or "",
                    "email": employee.get("email"),
                    "asignacion_adicional": employee.get("asignacion_adicional"),
                    "puestos_adicionales": len(employee.get("puestos_adicionales") or []),
                }
            )

    return rows


EXPORT_SPECS: dict[str, ExportSpec] = {
    "empresas.listado": ExportSpec(
        title="Empresas",
        filename_base="empresas",
        loader=lambda: _all_rows(get_empresas, include_inactive=True),
    ),
    "sucursales.listado": ExportSpec(
        title="Sucursales",
        filename_base="sucursales",
        loader=lambda: _all_rows(get_sucursales, include_inactive=True),
    ),
    "roles.listado": ExportSpec(
        title="Roles",
        filename_base="roles",
        loader=lambda: _page_rows(get_roles_page, search=_str_arg("q")),
    ),
    "empleado_roles.listado": ExportSpec(
        title="Empleados con roles",
        filename_base="empleado_roles",
        loader=lambda: _page_rows(
            get_page_for_roles,
            _int_arg("empresa_id"),
            _str_arg("q"),
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "empleado_horarios.listado": ExportSpec(
        title="Empleados con horarios",
        filename_base="empleado_horarios",
        loader=lambda: _all_rows(get_empleados, include_inactive=True),
    ),
    "asistencias.listado": ExportSpec(
        title="Asistencias",
        filename_base="asistencias",
        loader=lambda: _page_rows(
            get_asistencias_page,
            _int_arg("empleado_id"),
            _str_arg("fecha_desde"),
            _str_arg("fecha_hasta"),
            _str_arg("q"),
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "justificaciones.listado": ExportSpec(
        title="Justificaciones",
        filename_base="justificaciones",
        loader=lambda: _page_rows(
            get_justificaciones_page,
            _int_arg("empleado_id"),
            _str_arg("fecha_desde"),
            _str_arg("fecha_hasta"),
            _str_arg("q"),
            (_str_arg("estado") or None),
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "auditoria.listado": ExportSpec(
        title="Auditoria",
        filename_base="auditoria",
        loader=lambda: _page_rows(get_auditoria_page),
    ),
    "usuarios.listado": ExportSpec(
        title="Usuarios",
        filename_base="usuarios",
        loader=lambda: _page_rows(
            get_usuarios_page,
            _int_arg("empresa_id"),
            _tristate_arg("activo"),
            _str_arg("q"),
        ),
    ),
    "configuracion_empresa.listado": ExportSpec(
        title="Configuracion de empresa",
        filename_base="configuracion_empresa",
        loader=lambda: _all_rows(get_configuraciones_empresa),
    ),
    "sectores.listado": ExportSpec(
        title="Sectores",
        filename_base="sectores",
        loader=lambda: _page_rows(
            get_sectores_page,
            _int_arg("empresa_id"),
            _str_arg("q"),
            _tristate_arg("activo"),
        ),
    ),
    "puestos.listado": ExportSpec(
        title="Puestos",
        filename_base="puestos",
        loader=lambda: _page_rows(
            get_puestos_page,
            _int_arg("empresa_id"),
            _str_arg("q"),
            _tristate_arg("activo"),
        ),
    ),
    "organigrama.listado": ExportSpec(
        title="Organigrama",
        filename_base="organigrama",
        loader=_flatten_organigrama,
    ),
    "localidades.listado": ExportSpec(
        title="Localidades",
        filename_base="localidades",
        loader=lambda: _all_rows(get_localidades),
    ),
    "francos.listado": ExportSpec(
        title="Francos",
        filename_base="francos",
        loader=lambda: _all_rows(
            get_francos,
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "horarios.listado": ExportSpec(
        title="Horarios",
        filename_base="horarios",
        loader=lambda: _all_rows(get_horarios_resumen, include_inactive=True, sucursal_id=_int_arg("sucursal_id")),
    ),
    "app_version.listado": ExportSpec(
        title="Versiones de app",
        filename_base="app_version",
        loader=lambda: _all_rows(get_app_versions),
    ),
    "feedback_web.registros_listado": ExportSpec(
        title="Registros de feedback",
        filename_base="feedback_registros",
        loader=_load_feedback_registros_export,
    ),
    "feedback_web.motivos_listado": ExportSpec(
        title="Motivos de feedback",
        filename_base="feedback_motivos",
        loader=lambda: _page_rows(
            get_motivos_page,
            _str_arg("q"),
            _tristate_arg("activo"),
        ),
    ),
    "feedback_web.clientes_listado": ExportSpec(
        title="Clientes feedback",
        filename_base="feedback_clientes",
        loader=lambda: _page_rows(
            get_clientes_page,
            _str_arg("q"),
            _tristate_arg("activo"),
        ),
    ),
    "calificaciones_app.listado": ExportSpec(
        title="Calificaciones app",
        filename_base="calificaciones_app",
        loader=lambda: _page_rows(
            get_calificaciones_page,
            fecha_desde=_str_arg("fecha_desde"),
            fecha_hasta=_str_arg("fecha_hasta"),
            sector_id=_int_arg("sector_id"),
            version_app=_str_arg("version_app"),
            puntuacion=_int_arg("puntuacion"),
        ),
    ),
    "mobile_stats.listado": ExportSpec(
        title="Sesiones mobile",
        filename_base="mobile_stats",
        loader=lambda: _page_rows(
            get_sesiones_page,
            fecha_desde=_str_arg("fecha_desde"),
            fecha_hasta=_str_arg("fecha_hasta"),
            platform=_str_arg("platform"),
            app_version=_str_arg("app_version"),
            empleado_q=_str_arg("q"),
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "empleado_excepciones.listado": ExportSpec(
        title="Excepciones de empleados",
        filename_base="empleado_excepciones",
        loader=lambda: _all_rows(
            get_excepciones,
            empleado_id=_int_arg("empleado_id"),
            fecha_desde=_str_arg("fecha_desde"),
            fecha_hasta=_str_arg("fecha_hasta"),
            tipo=_str_arg("tipo"),
            anula_horario=_tristate_arg("anula_horario"),
            order_by=_str_arg("orden") or "fecha_desc",
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "legajo_tipos_evento.listado": ExportSpec(
        title="Tipos de evento",
        filename_base="legajo_tipos_evento",
        loader=lambda: _page_rows(
            get_tipos_evento_page,
            search=_str_arg("q"),
            activo=_tristate_arg("activo"),
        ),
    ),
    "legajos.listado_empleados": ExportSpec(
        title="Legajos de empleados",
        filename_base="legajos_empleados",
        loader=lambda: _all_rows(
            get_empleados,
            include_inactive=True,
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "legajos.listado_eventos": ExportSpec(
        title="Eventos de legajo",
        filename_base="legajos_eventos",
        loader=lambda: _page_rows(
            get_eventos_page,
            search=_str_arg("q"),
            empresa_id=_int_arg("empresa_id"),
            empleado_id=_int_arg("empleado_id"),
            tipo_id=_int_arg("tipo_id"),
            estado=_parse_legajo_evento_estado(),
            sucursal_id=_int_arg("sucursal_id"),
            sector_id=_int_arg("sector_id"),
        ),
    ),
    "vacaciones.listado": ExportSpec(
        title="Movimientos de vacaciones",
        filename_base="vacaciones_movimientos",
        loader=_load_vacaciones_export,
    ),
    "adelantos.listado": ExportSpec(
        title="Adelantos",
        filename_base="adelantos",
        loader=lambda: _all_rows(
            get_adelantos_export,
            empleado_id=_int_arg("empleado_id"),
            q=_str_arg("q"),
            estado=_str_arg("estado"),
            anio=_int_arg("anio"),
            mes=_int_arg("mes"),
        ),
    ),
    "pedidos_mercaderia.listado": ExportSpec(
        title="Pedidos de mercaderia",
        filename_base="pedidos_mercaderia",
        loader=lambda: _all_rows(
            get_pedidos_export,
            empleado_id=_int_arg("empleado_id"),
            q=_str_arg("q"),
            estado=_str_arg("estado"),
            anio=_int_arg("anio"),
            mes=_int_arg("mes"),
        ),
    ),
    "premios_concursos.listado": ExportSpec(
        title="Concursos",
        filename_base="premios_concursos",
        loader=_load_concursos_export,
    ),
    "trivia_admin.listado": ExportSpec(
        title="Trivias",
        filename_base="trivias",
        loader=lambda: _page_rows(
            get_trivias_page,
            estado=_str_arg("estado"),
            anio=_int_arg("anio"),
        ),
    ),
    "qr_puerta.generar": ExportSpec(
        title="Historial de QR de puerta",
        filename_base="qr_puerta_historial",
        loader=lambda: _all_rows(get_qr_historial_recent, limit=5000, empresa_id=_int_arg("empresa_id")),
    ),
    "skap_web.evaluaciones_listado": ExportSpec(
        title="Evaluaciones SKAP",
        filename_base="skap_evaluaciones",
        loader=lambda: _page_rows(
            get_evaluaciones_page,
            anio=_int_arg("anio"),
            sector_id=_int_arg("sector_id"),
            sucursal_id=_int_arg("sucursal_id"),
            search=_str_arg("q"),
        ),
    ),
    "skap_web.planes_listado": ExportSpec(
        title="Planes de desarrollo SKAP",
        filename_base="skap_planes",
        loader=lambda: _page_rows(
            get_planes_page,
            anio=_int_arg("anio"),
            sector_id=_int_arg("sector_id"),
            sucursal_id=_int_arg("sucursal_id"),
            search=_str_arg("q"),
        ),
    ),
    "kpis_sectoriales.listado": ExportSpec(
        title="KPIs por sector",
        filename_base="kpis_sectoriales",
        loader=_load_kpis_export,
        toolbar_enabled=lambda: bool(_int_arg("sector_id") and _int_arg("sector_id") > 0),
        disabled_message="Seleccione una empresa y un sector para exportar los KPIs.",
    ),
}


def _required_roles(view_func: Callable[..., Any]) -> tuple[str, ...]:
    closure = getattr(view_func, "__closure__", None) or ()
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if isinstance(value, tuple) and value and all(isinstance(item, str) for item in value):
            return tuple(value)
    return ()


def _enforce_roles(view_func: Callable[..., Any]):
    roles = _required_roles(view_func)
    if not roles:
        return

    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("web_auth.login"))

    if not any(auth_decorators.has_role(user_id, role) for role in roles):
        abort(403)


def build_export_toolbar(endpoint: str | None) -> dict[str, Any]:
    spec = EXPORT_SPECS.get(endpoint or "")
    if not spec or not spec.toolbar_enabled():
        return {"enabled": False, "items": []}

    query_args = request.args.to_dict(flat=True)
    for key in ("page", "per", "per_page", "export"):
        query_args.pop(key, None)

    items = []
    for export_format, label in (("xlsx", "Excel"), ("pdf", "PDF")):
        try:
            items.append(
                {
                    "label": label,
                    "format": export_format,
                    "url": url_for(endpoint, export=export_format, **query_args),
                }
            )
        except Exception:
            continue

    return {"enabled": bool(items), "items": items}


def wrap_exportable_views(app):
    for endpoint, spec in EXPORT_SPECS.items():
        view_func = app.view_functions.get(endpoint)
        if not view_func:
            continue

        if getattr(view_func, "__panel_export_wrapped__", False):
            continue

        @wraps(view_func)
        def _wrapped(*args, __view_func=view_func, __spec=spec, __endpoint=endpoint, **kwargs):
            export_format = normalize_export_format(request.args.get("export"))
            if export_format not in {"xlsx", "pdf"}:
                return __view_func(*args, **kwargs)

            if not __spec.toolbar_enabled():
                abort(400, description=__spec.disabled_message)

            auth_result = _enforce_roles(__view_func)
            if auth_result is not None:
                return auth_result

            try:
                rows = list(__spec.loader() or [])
                export_file = build_table_export(__spec.title, rows, export_format)
                filename = f"{__spec.filename_base}.{export_file.filename}"
                return build_attachment_response(
                    export_file.data,
                    filename=filename,
                    mimetype=export_file.mimetype,
                )
            except Exception:
                current_app.logger.exception(
                    "panel_export_error",
                    extra={
                        "extra": {
                            "endpoint": __endpoint,
                            "export_format": export_format,
                        }
                    },
                )
                return current_app.response_class(
                    "Error al generar la exportacion.",
                    status=500,
                    mimetype="text/plain",
                )

        _wrapped.__panel_export_wrapped__ = True
        app.view_functions[endpoint] = _wrapped
