import datetime
import decimal
import hmac
import math
import os

from flask import Blueprint, Response, jsonify, request

from repositories.asistencia_marca_repository import (
    get_for_export_admin as get_marcas_admin_export,
)
from repositories.external_api_repository import (
    get_empresas as get_empresas_external,
    get_sucursales as get_sucursales_external,
    list_empleados as list_empleados_external,
)
from services.asistencia_reporte_service import build_asistencia_reporte_csv
from services.external_api_auth_service import (
    EXTERNAL_API_SCOPE,
    ExternalApiAuthConfigError,
    ExternalApiTokenError,
    authenticate_external_credentials,
    external_credentials_configured,
    issue_external_access_token,
    verify_external_access_token,
)
from utils.limiter import limiter

external_api_bp = Blueprint("external_api", __name__, url_prefix="/api/v1/external")

_ESTADOS_EMPLEADO = {"activo", "inactivo", "suspendido"}
_ALL_VALUES = {"all", "todos", "todas", "*"}
_TRUE_VALUES = {"1", "true", "yes", "si", "s", "on", "activo", "activa"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "inactivo", "inactiva"}


def _configured_api_key() -> str | None:
    key = (os.getenv("EXTERNAL_API_KEY") or os.getenv("INTEGRATION_API_KEY") or "").strip()
    return key or None


def _request_api_key() -> str:
    return (request.headers.get("X-API-Key") or "").strip()


def _request_bearer_token() -> str:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _api_auth_error(message: str, status_code: int):
    response = jsonify({"error": message})
    response.headers["WWW-Authenticate"] = 'ApiKey realm="external"'
    response.headers.add("WWW-Authenticate", 'Bearer realm="external"')
    return response, status_code


@external_api_bp.before_request
def _require_external_api_key():
    if request.method == "OPTIONS" or request.endpoint == "external_api.auth_token":
        return None

    expected_key = _configured_api_key()
    if not expected_key and not external_credentials_configured():
        return jsonify({
            "error": "EXTERNAL_API_KEY o credenciales de API externa no configuradas."
        }), 503

    provided_key = _request_api_key()
    if provided_key:
        if expected_key and hmac.compare_digest(provided_key, expected_key):
            return None
        return _api_auth_error("API key invalida o ausente.", 401)

    bearer_token = _request_bearer_token()
    if bearer_token:
        if expected_key and hmac.compare_digest(bearer_token, expected_key):
            return None
        try:
            verify_external_access_token(bearer_token)
            return None
        except ExternalApiAuthConfigError as exc:
            return jsonify({"error": str(exc)}), 503
        except ExternalApiTokenError:
            return _api_auth_error("API key invalida o ausente.", 401)

    return _api_auth_error("API key invalida o ausente.", 401)


@external_api_bp.route("/auth/token", methods=["POST"])
@limiter.limit("5 per minute")
def auth_token():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not username or not password:
        return jsonify({"error": "username y password son requeridos."}), 400

    try:
        authenticated = authenticate_external_credentials(username, password)
        if not authenticated:
            return _api_auth_error("Credenciales invalidas.", 401)
        token, expires_in = issue_external_access_token(username)
    except ExternalApiAuthConfigError as exc:
        return jsonify({"error": str(exc)}), 503

    response = jsonify({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": EXTERNAL_API_SCOPE,
    })
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _split_values(*names: str) -> list[str]:
    values = []
    for name in names:
        for raw in request.args.getlist(name):
            for part in str(raw or "").split(","):
                value = part.strip()
                if value:
                    values.append(value)
    return values


def _parse_optional_int(name: str) -> tuple[int | None, str | None]:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"{name} debe ser numerico."
    if value <= 0:
        return None, f"{name} debe ser mayor a cero."
    return value, None


def _parse_int_values(*names: str) -> tuple[list[int], str | None]:
    values = []
    seen = set()
    for raw in _split_values(*names):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return [], f"{'/'.join(names)} debe contener IDs numericos."
        if value <= 0:
            return [], f"{'/'.join(names)} debe contener IDs mayores a cero."
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values, None


def _parse_activo(name: str, *, default: int | None = 1) -> tuple[int | None, str | None]:
    raw = (request.args.get(name) or "").strip().lower()
    if not raw:
        return default, None
    if raw in _ALL_VALUES:
        return None, None
    if raw in _TRUE_VALUES:
        return 1, None
    if raw in _FALSE_VALUES:
        return 0, None
    return None, f"{name} debe ser 1, 0 o all."


def _parse_estados() -> tuple[list[str] | None, bool, str | None]:
    raw_values = _split_values("estado", "estados")
    if not raw_values:
        return None, False, None

    estados = []
    seen = set()
    for raw in raw_values:
        value = raw.strip().lower()
        if value in _ALL_VALUES:
            return None, True, None
        if value not in _ESTADOS_EMPLEADO:
            allowed = ", ".join(sorted(_ESTADOS_EMPLEADO))
            return None, False, f"estado invalido. Use {allowed} o all."
        if value not in seen:
            seen.add(value)
            estados.append(value)
    return estados, False, None


def _parse_page() -> tuple[int, int, str | None]:
    page_raw = (request.args.get("page") or "1").strip()
    per_raw = (
        request.args.get("per_page")
        or request.args.get("per")
        or request.args.get("limit")
        or "100"
    )
    try:
        page = int(page_raw)
        per_page = int(str(per_raw).strip())
    except (TypeError, ValueError):
        return 1, 100, "page y per_page deben ser numericos."
    if page <= 0:
        return 1, 100, "page debe ser mayor a cero."
    if per_page <= 0:
        return 1, 100, "per_page debe ser mayor a cero."
    return page, min(per_page, 500), None


def _json_value(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def _serialize_row(row: dict) -> dict:
    return {key: _json_value(value) for key, value in row.items()}


def _serialize_bool(row: dict, field: str):
    if field in row and row[field] is not None:
        row[field] = bool(row[field])


def _serialize_empresa(row: dict) -> dict:
    payload = _serialize_row(row)
    _serialize_bool(payload, "activa")
    return payload


def _serialize_sucursal(row: dict) -> dict:
    payload = _serialize_row(row)
    _serialize_bool(payload, "activa")
    return payload


def _serialize_empleado(row: dict) -> dict:
    payload = _serialize_row(row)
    _serialize_bool(payload, "activo")
    reporta_a_nombre = str(payload.get("reporta_a_nombre") or "").strip()
    payload["reporta_a_nombre"] = reporta_a_nombre or None

    ids = str(payload.get("puestos_adicionales_ids") or "").strip()
    payload["puestos_adicionales_ids"] = [
        int(value)
        for value in ids.split(",")
        if value.strip().isdigit()
    ]

    nombres = str(payload.get("puestos_adicionales_nombres") or "").strip()
    payload["puestos_adicionales_nombres"] = [
        value.strip()
        for value in nombres.split(",")
        if value.strip()
    ]
    return payload


def _empleados_query_params():
    empresa_id, error = _parse_optional_int("empresa_id")
    if error:
        return None, error

    sucursal_ids, error = _parse_int_values("sucursal_id", "sucursales_id")
    if error:
        return None, error

    puesto_ids, error = _parse_int_values("puesto_id", "puestos_id")
    if error:
        return None, error

    estados, estado_all, error = _parse_estados()
    if error:
        return None, error

    activo, error = _parse_activo("activo", default=1)
    if error:
        return None, error

    if estados:
        activo = None
    elif estado_all and "activo" not in request.args:
        activo = None

    page, per_page, error = _parse_page()
    if error:
        return None, error

    return {
        "page": page,
        "per_page": per_page,
        "empresa_id": empresa_id,
        "sucursal_ids": sucursal_ids,
        "sucursal_nombres": _split_values("sucursal", "sucursal_nombre", "sucursales"),
        "estados": estados,
        "activo": activo,
        "puesto_ids": puesto_ids,
        "puesto_nombres": _split_values("tipo_empleado", "tipo", "puesto", "puestos"),
        "search": (request.args.get("q") or "").strip() or None,
    }, None


def _pagination(page: int, per_page: int, total: int) -> dict:
    pages = math.ceil(total / per_page) if per_page else 0
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
    }


def _parse_optional_date(name: str) -> tuple[str | None, str | None]:
    raw = str(request.args.get(name) or "").strip()
    if not raw:
        return None, None
    try:
        return datetime.date.fromisoformat(raw).isoformat(), None
    except ValueError:
        return None, f"{name} debe usar formato YYYY-MM-DD."


def _report_filters() -> tuple[dict | None, str | None]:
    empresa_id, error = _parse_optional_int("empresa_id")
    if error:
        return None, error
    empleado_id, error = _parse_optional_int("empleado_id")
    if error:
        return None, error
    fecha_desde, error = _parse_optional_date("fecha_desde")
    if error:
        return None, error
    fecha_hasta, error = _parse_optional_date("fecha_hasta")
    if error:
        return None, error
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        return None, "fecha_desde no puede ser posterior a fecha_hasta."

    gps_ok, error = _parse_activo("gps_ok", default=None)
    if error:
        return None, error

    limit_raw = str(request.args.get("limit") or "20000").strip()
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return None, "limit debe ser numerico."
    if limit <= 0:
        return None, "limit debe ser mayor a cero."

    return {
        "empresa_id": empresa_id,
        "empleado_id": empleado_id,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "tipo_marca": str(request.args.get("tipo_marca") or "").strip() or None,
        "accion": str(request.args.get("accion") or "").strip() or None,
        "metodo": str(request.args.get("metodo") or "").strip() or None,
        "search": str(request.args.get("q") or "").strip() or None,
        "gps_ok": gps_ok,
        "limit": min(limit, 20000),
        "order_asc": True,
    }, None


@external_api_bp.route("/empresas", methods=["GET"])
def empresas():
    activa, error = _parse_activo("activa", default=1)
    if error:
        return jsonify({"error": error}), 400
    rows = get_empresas_external(activa=activa)
    data = [_serialize_empresa(row) for row in rows]
    return jsonify({"data": data, "count": len(data)})


@external_api_bp.route("/sucursales", methods=["GET"])
def sucursales():
    empresa_id, error = _parse_optional_int("empresa_id")
    if error:
        return jsonify({"error": error}), 400
    activa, error = _parse_activo("activa", default=1)
    if error:
        return jsonify({"error": error}), 400
    rows = get_sucursales_external(empresa_id=empresa_id, activa=activa)
    data = [_serialize_sucursal(row) for row in rows]
    return jsonify({"data": data, "count": len(data)})


@external_api_bp.route("/empleados", methods=["GET"])
def empleados():
    params, error = _empleados_query_params()
    if error:
        return jsonify({"error": error}), 400
    rows, total = list_empleados_external(**params)
    data = [_serialize_empleado(row) for row in rows]
    return jsonify({
        "data": data,
        "pagination": _pagination(params["page"], params["per_page"], total),
    })


@external_api_bp.route("/catalogo", methods=["GET"])
def catalogo():
    params, error = _empleados_query_params()
    if error:
        return jsonify({"error": error}), 400

    empresas_activa, error = _parse_activo("empresas_activa", default=1)
    if error:
        return jsonify({"error": error}), 400
    sucursales_activa, error = _parse_activo("sucursales_activa", default=1)
    if error:
        return jsonify({"error": error}), 400

    empresas_rows = get_empresas_external(activa=empresas_activa)
    sucursales_rows = get_sucursales_external(
        empresa_id=params["empresa_id"],
        activa=sucursales_activa,
    )
    empleados_rows, empleados_total = list_empleados_external(**params)

    return jsonify({
        "empresas": [_serialize_empresa(row) for row in empresas_rows],
        "sucursales": [_serialize_sucursal(row) for row in sucursales_rows],
        "empleados": [_serialize_empleado(row) for row in empleados_rows],
        "counts": {
            "empresas": len(empresas_rows),
            "sucursales": len(sucursales_rows),
            "empleados": empleados_total,
        },
        "empleados_pagination": _pagination(
            params["page"],
            params["per_page"],
            empleados_total,
        ),
    })


@external_api_bp.route("/reportes/asistencia.csv", methods=["GET"])
@limiter.limit("30 per minute")
def reporte_asistencia_csv():
    filters, error = _report_filters()
    if error:
        return jsonify({"error": error}), 400

    rows = get_marcas_admin_export(**filters)
    csv_content = build_asistencia_reporte_csv(rows)
    filename = f"reporte_asistencia_{datetime.date.today().isoformat()}.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Report-Row-Count": str(len(rows)),
        },
    )
