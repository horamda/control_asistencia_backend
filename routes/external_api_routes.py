import datetime
import decimal
import hmac
import math
import os

from flask import Blueprint, jsonify, request

from repositories.external_api_repository import (
    get_empresas as get_empresas_external,
    get_sucursales as get_sucursales_external,
    list_empleados as list_empleados_external,
)

external_api_bp = Blueprint("external_api", __name__, url_prefix="/api/v1/external")

_ESTADOS_EMPLEADO = {"activo", "inactivo", "suspendido"}
_ALL_VALUES = {"all", "todos", "todas", "*"}
_TRUE_VALUES = {"1", "true", "yes", "si", "s", "on", "activo", "activa"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "inactivo", "inactiva"}


def _configured_api_key() -> str | None:
    key = (os.getenv("EXTERNAL_API_KEY") or os.getenv("INTEGRATION_API_KEY") or "").strip()
    return key or None


def _request_api_key() -> str:
    header_key = (request.headers.get("X-API-Key") or "").strip()
    if header_key:
        return header_key

    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _api_auth_error(message: str, status_code: int):
    response = jsonify({"error": message})
    response.headers["WWW-Authenticate"] = 'ApiKey realm="external"'
    return response, status_code


@external_api_bp.before_request
def _require_external_api_key():
    if request.method == "OPTIONS":
        return None

    expected_key = _configured_api_key()
    if not expected_key:
        return jsonify({"error": "EXTERNAL_API_KEY no configurada."}), 503

    provided_key = _request_api_key()
    if not provided_key or not hmac.compare_digest(provided_key, expected_key):
        return _api_auth_error("API key invalida o ausente.", 401)
    return None


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
