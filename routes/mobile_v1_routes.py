import datetime
import math

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from repositories.asistencia_repository import (
    get_by_empleado_fecha,
    get_page_by_empleado,
    register_entrada,
    register_salida,
)
from repositories.configuracion_empresa_repository import get_by_empresa_id
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.empleado_repository import (
    update_mobile_profile,
    update_password as update_empleado_password,
)
from repositories.sucursal_repository import get_by_id as get_sucursal_by_id
from services.auth_service import authenticate_user
from utils.asistencia import get_horario_esperado, validar_asistencia
from utils.jwt import generar_token, generar_token_qr, verificar_token_qr
from utils.jwt_guard import mobile_auth_required
from utils.qr import build_qr_png_base64

mobile_v1_bp = Blueprint("mobile_v1", __name__, url_prefix="/api/v1/mobile")


def _today_iso():
    return datetime.date.today().isoformat()


def _now_hhmm():
    return datetime.datetime.now().strftime("%H:%M")


def _parse_date(value: str | None):
    raw = (value or "").strip()
    if not raw:
        return None
    datetime.date.fromisoformat(raw)
    return raw


def _parse_hhmm(value: str | None):
    raw = (value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if len(raw) == 5:
        candidates.append(f"{raw}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return parsed.strftime("%H:%M")
        except ValueError:
            pass
    raise ValueError("Hora invalida. Use HH:MM.")


def _parse_float(value, label):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalido.") from exc


def _validate_geo(lat, lon):
    if lat is not None and (lat < -90 or lat > 90):
        raise ValueError("Latitud fuera de rango.")
    if lon is not None and (lon < -180 or lon > 180):
        raise ValueError("Longitud fuera de rango.")


def _parse_int(value, label: str, default=None):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalido.") from exc


def _to_hhmm(value):
    if value is None:
        return None
    if isinstance(value, datetime.timedelta):
        mins = int(value.total_seconds() // 60)
        return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 5:
        return text[:5]
    return text


def _to_date_str(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _mobile_user():
    empleado_id = int(g.mobile_empleado_id)
    empleado = get_empleado_by_id(empleado_id)
    if not empleado or not empleado.get("activo"):
        return None
    return empleado


def _check_config_metodo(empresa_id: int, metodo: str, lat, lon, foto):
    config = get_by_empresa_id(empresa_id)
    if not config:
        return

    if config.get("requiere_qr") and metodo != "qr":
        raise ValueError("La empresa requiere metodo QR.")
    if config.get("requiere_foto") and not foto:
        raise ValueError("La empresa requiere foto para fichar.")
    if config.get("requiere_geo") and (lat is None or lon is None):
        raise ValueError("La empresa requiere geolocalizacion para fichar.")


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _geo_ref_from_qr_payload(qr_payload):
    geo_ref = qr_payload.get("geo_ref") if isinstance(qr_payload, dict) else None
    if not isinstance(geo_ref, dict):
        return None
    lat = geo_ref.get("lat")
    lon = geo_ref.get("lon")
    radio_m = geo_ref.get("radio_m")
    if lat is None or lon is None or radio_m is None:
        return None
    try:
        return {
            "lat": float(lat),
            "lon": float(lon),
            "radio_m": float(radio_m),
            "sucursal_id": geo_ref.get("sucursal_id"),
        }
    except (TypeError, ValueError):
        return None


def _geo_ref_from_empleado(empleado):
    sucursal_id = empleado.get("sucursal_id")
    if not sucursal_id:
        return None
    sucursal = get_sucursal_by_id(int(sucursal_id))
    if not sucursal:
        return None
    lat = sucursal.get("latitud")
    lon = sucursal.get("longitud")
    radio_m = sucursal.get("radio_permitido_m")
    if lat is None or lon is None or radio_m is None:
        return None
    try:
        return {
            "lat": float(lat),
            "lon": float(lon),
            "radio_m": float(radio_m),
            "sucursal_id": sucursal.get("id"),
        }
    except (TypeError, ValueError):
        return None


def _validar_geo_scan_qr(empleado, qr_payload, lat, lon):
    if lat is None or lon is None:
        raise ValueError("lat y lon son requeridos para escanear QR.")

    geo_ref = _geo_ref_from_qr_payload(qr_payload) or _geo_ref_from_empleado(empleado)
    if not geo_ref:
        raise ValueError("No hay geocerca configurada para validar este QR.")

    distancia_m = _haversine_m(float(lat), float(lon), geo_ref["lat"], geo_ref["lon"])
    tolerancia_m = float(geo_ref["radio_m"])
    gps_ok = distancia_m <= tolerancia_m
    return {
        "gps_ok": gps_ok,
        "distancia_m": round(distancia_m, 2),
        "tolerancia_m": round(tolerancia_m, 2),
        "ref_lat": geo_ref["lat"],
        "ref_lon": geo_ref["lon"],
        "sucursal_id": geo_ref.get("sucursal_id"),
    }


def _validar_qr_fichada(empleado, qr_token: str | None, accion: str | None):
    token = (qr_token or "").strip()
    if not token:
        raise ValueError("qr_token requerido para metodo qr.")

    payload = verificar_token_qr(token, accion_esperada=accion)
    token_empresa = int(payload.get("empresa_id"))
    if token_empresa != int(empleado["empresa_id"]):
        raise ValueError("QR no corresponde a la empresa del empleado.")

    token_empleado = payload.get("empleado_id")
    if token_empleado is not None and int(token_empleado) != int(empleado["id"]):
        raise ValueError("QR no corresponde al empleado autenticado.")
    return payload


@mobile_v1_bp.route("/auth/login", methods=["POST"])
def auth_login():
    payload = request.get_json(silent=True) or {}
    dni = str(payload.get("dni") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not dni or not password:
        return jsonify({"error": "dni y password son requeridos"}), 400

    user, error = authenticate_user(dni, password)
    if error:
        return jsonify({"error": error}), 401

    token = generar_token(
        {
            "empleado_id": user["id"],
            "user_id": user["id"],
            "dni": user["dni"],
            "nombre": user["nombre"],
        }
    )
    return jsonify(
        {
            "token": token,
            "empleado": {
                "id": user["id"],
                "dni": user["dni"],
                "nombre": user.get("nombre"),
                "apellido": user.get("apellido"),
                "empresa_id": user.get("empresa_id"),
            },
        }
    )


@mobile_v1_bp.route("/auth/refresh", methods=["POST"])
@mobile_auth_required
def auth_refresh():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    token = generar_token(
        {
            "empleado_id": empleado["id"],
            "user_id": empleado["id"],
            "dni": empleado["dni"],
            "nombre": empleado["nombre"],
        }
    )
    return jsonify({"token": token})


@mobile_v1_bp.route("/me", methods=["GET"])
@mobile_auth_required
def me():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    return jsonify(
        {
            "id": empleado["id"],
            "empresa_id": empleado.get("empresa_id"),
            "sucursal_id": empleado.get("sucursal_id"),
            "sector_id": empleado.get("sector_id"),
            "puesto_id": empleado.get("puesto_id"),
            "dni": empleado.get("dni"),
            "legajo": empleado.get("legajo"),
            "nombre": empleado.get("nombre"),
            "apellido": empleado.get("apellido"),
            "email": empleado.get("email"),
            "telefono": empleado.get("telefono"),
            "direccion": empleado.get("direccion"),
            "foto": empleado.get("foto"),
            "estado": empleado.get("estado"),
        }
    )


@mobile_v1_bp.route("/me/config-asistencia", methods=["GET"])
@mobile_auth_required
def me_config_asistencia():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    config = get_by_empresa_id(empleado["empresa_id"]) or {}
    return jsonify(
        {
            "empresa_id": empleado["empresa_id"],
            "requiere_qr": bool(config.get("requiere_qr")),
            "requiere_foto": bool(config.get("requiere_foto")),
            "requiere_geo": bool(config.get("requiere_geo")),
            "tolerancia_global": config.get("tolerancia_global"),
            "metodos_habilitados": ["qr", "manual", "facial"],
        }
    )


@mobile_v1_bp.route("/me/qr", methods=["POST"])
@mobile_auth_required
def me_generar_qr():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    accion = str(payload.get("accion") or "auto").strip().lower()
    if accion not in {"ingreso", "egreso", "auto"}:
        return jsonify({"error": "accion invalida. Use ingreso, egreso o auto."}), 400

    scope = str(payload.get("scope") or "empresa").strip().lower()
    if scope not in {"empresa", "empleado"}:
        return jsonify({"error": "scope invalido. Use empresa o empleado."}), 400

    try:
        vigencia_segundos = _parse_int(payload.get("vigencia_segundos"), "vigencia_segundos", 120)
        if vigencia_segundos < 30 or vigencia_segundos > 315360000:
            return jsonify({"error": "vigencia_segundos fuera de rango (30-315360000)."}), 400

        qr_payload = {
            "accion": accion,
            "empresa_id": empleado["empresa_id"],
            "scope": scope,
        }
        if scope == "empleado":
            qr_payload["empleado_id"] = empleado["id"]

        qr_token = generar_token_qr(qr_payload, vigencia_segundos=vigencia_segundos)
        qr_image_base64 = build_qr_png_base64(qr_token)
        expira_at = (
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=vigencia_segundos)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return jsonify(
            {
                "accion": accion,
                "scope": scope,
                "empresa_id": empleado["empresa_id"],
                "empleado_id": empleado["id"] if scope == "empleado" else None,
                "vigencia_segundos": vigencia_segundos,
                "expira_at": expira_at,
                "qr_token": qr_token,
                "qr_png_base64": qr_image_base64,
            }
        )
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@mobile_v1_bp.route("/me/fichadas/scan", methods=["POST"])
@mobile_auth_required
def fichar_scan_qr():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    fecha = (payload.get("fecha") or "").strip() or _today_iso()
    hora = str(payload.get("hora") or "").strip() or _now_hhmm()
    foto = str(payload.get("foto") or "").strip() or None
    qr_token = str(payload.get("qr_token") or "").strip() or None
    observaciones = str(payload.get("observaciones") or "").strip() or None
    lat = _parse_float(payload.get("lat"), "Latitud")
    lon = _parse_float(payload.get("lon"), "Longitud")
    _validate_geo(lat, lon)

    try:
        _parse_date(fecha)
        hora = _parse_hhmm(hora)
        _check_config_metodo(empleado["empresa_id"], "qr", lat, lon, foto)
        qr_payload = _validar_qr_fichada(empleado, qr_token, None)
        geo = _validar_geo_scan_qr(empleado, qr_payload, lat, lon)
        if not geo["gps_ok"]:
            current_app.logger.info(
                "scan_qr_geo_rechazado",
                extra={
                    "extra": {
                        "empleado_id": empleado["id"],
                        "empresa_id": empleado["empresa_id"],
                        "lat": lat,
                        "lon": lon,
                        "ref_lat": geo["ref_lat"],
                        "ref_lon": geo["ref_lon"],
                        "distancia_m": geo["distancia_m"],
                        "tolerancia_m": geo["tolerancia_m"],
                        "sucursal_id": geo.get("sucursal_id"),
                        "fecha": fecha,
                        "hora": hora,
                    }
                },
            )
            return (
                jsonify(
                    {
                        "error": "Ubicacion fuera del rango permitido para fichar.",
                        "gps_ok": False,
                        "distancia_m": geo["distancia_m"],
                        "tolerancia_m": geo["tolerancia_m"],
                    }
                ),
                403,
            )

        gps_note = (
            f"gps_ok=1;dist_m={geo['distancia_m']};tol_m={geo['tolerancia_m']};"
            f"ref={geo['ref_lat']},{geo['ref_lon']}"
        )
        observaciones = f"{observaciones} | {gps_note}" if observaciones else gps_note

        accion_qr = str(qr_payload.get("accion") or "auto").strip().lower()
        row = get_by_empleado_fecha(empleado["id"], fecha)
        if accion_qr in {"ingreso", "egreso"}:
            accion = accion_qr
        elif not row or row.get("hora_entrada") is None:
            accion = "ingreso"
        elif row.get("hora_salida") is None:
            accion = "egreso"
        else:
            return jsonify({"error": "Ya existe entrada y salida registradas para esa fecha."}), 409

        if accion == "ingreso":
            _, estado_calc = validar_asistencia(empleado["id"], fecha, hora, None)
            estado = estado_calc or "ok"
            asistencia_id = register_entrada(
                empleado_id=empleado["id"],
                fecha=fecha,
                hora_entrada=hora,
                metodo_entrada="qr",
                lat_entrada=lat,
                lon_entrada=lon,
                foto_entrada=foto,
                estado=estado,
                observaciones=observaciones,
                gps_ok_entrada=True,
                gps_distancia_entrada_m=geo["distancia_m"],
                gps_tolerancia_entrada_m=geo["tolerancia_m"],
                gps_ref_lat_entrada=geo["ref_lat"],
                gps_ref_lon_entrada=geo["ref_lon"],
            )
            return (
                jsonify(
                    {
                        "id": asistencia_id,
                        "accion": "ingreso",
                        "estado": estado,
                        "gps_ok": True,
                        "distancia_m": geo["distancia_m"],
                        "tolerancia_m": geo["tolerancia_m"],
                    }
                ),
                201,
            )

        hora_entrada = _to_hhmm(row.get("hora_entrada")) if row else None
        _, estado_calc = validar_asistencia(empleado["id"], fecha, hora_entrada, hora)
        estado = estado_calc or "ok"
        asistencia_id = register_salida(
            empleado_id=empleado["id"],
            fecha=fecha,
            hora_salida=hora,
            metodo_salida="qr",
            lat_salida=lat,
            lon_salida=lon,
            foto_salida=foto,
            estado=estado,
            observaciones=observaciones,
            gps_ok_salida=True,
            gps_distancia_salida_m=geo["distancia_m"],
            gps_tolerancia_salida_m=geo["tolerancia_m"],
            gps_ref_lat_salida=geo["ref_lat"],
            gps_ref_lon_salida=geo["ref_lon"],
        )
        return jsonify(
            {
                "id": asistencia_id,
                "accion": "egreso",
                "estado": estado,
                "gps_ok": True,
                "distancia_m": geo["distancia_m"],
                "tolerancia_m": geo["tolerancia_m"],
            }
        )
    except ValueError as exc:
        message = str(exc)
        code = 409 if "ya registrada" in message else 400
        if "No hay fichada de entrada" in message:
            code = 404
        return jsonify({"error": message}), code


@mobile_v1_bp.route("/me/horario-esperado", methods=["GET"])
@mobile_auth_required
def me_horario_esperado():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    fecha = (request.args.get("fecha") or "").strip() or _today_iso()
    try:
        _parse_date(fecha)
        data = get_horario_esperado(empleado["id"], fecha)
    except ValueError:
        return jsonify({"error": "fecha invalida"}), 400

    if not data:
        return jsonify({"error": "sin horario esperado"}), 404
    return jsonify(data)


@mobile_v1_bp.route("/me/asistencias", methods=["GET"])
@mobile_auth_required
def me_asistencias():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per", 20, type=int) or 20
    per_page = max(1, min(per_page, 100))
    fecha_desde = (request.args.get("desde") or "").strip() or None
    fecha_hasta = (request.args.get("hasta") or "").strip() or None
    try:
        if fecha_desde:
            _parse_date(fecha_desde)
        if fecha_hasta:
            _parse_date(fecha_hasta)
    except ValueError:
        return jsonify({"error": "Rango de fechas invalido"}), 400

    rows, total = get_page_by_empleado(
        empleado_id=empleado["id"],
        page=page,
        per_page=per_page,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    serialized = []
    for r in rows:
        serialized.append(
            {
                "id": r["id"],
                "fecha": _to_date_str(r["fecha"]),
                "hora_entrada": _to_hhmm(r.get("hora_entrada")),
                "hora_salida": _to_hhmm(r.get("hora_salida")),
                "metodo_entrada": r.get("metodo_entrada"),
                "metodo_salida": r.get("metodo_salida"),
                "estado": r.get("estado"),
                "observaciones": r.get("observaciones"),
                "gps_ok_entrada": bool(r.get("gps_ok_entrada")) if r.get("gps_ok_entrada") is not None else None,
                "gps_ok_salida": bool(r.get("gps_ok_salida")) if r.get("gps_ok_salida") is not None else None,
                "gps_distancia_entrada_m": r.get("gps_distancia_entrada_m"),
                "gps_distancia_salida_m": r.get("gps_distancia_salida_m"),
                "gps_tolerancia_entrada_m": r.get("gps_tolerancia_entrada_m"),
                "gps_tolerancia_salida_m": r.get("gps_tolerancia_salida_m"),
            }
        )

    return jsonify(
        {
            "items": serialized,
            "page": page,
            "per_page": per_page,
            "total": total,
        }
    )


@mobile_v1_bp.route("/me/fichadas/entrada", methods=["POST"])
@mobile_auth_required
def fichar_entrada():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    fecha = (payload.get("fecha") or "").strip() or _today_iso()
    metodo = str(payload.get("metodo") or "").strip().lower()
    hora_entrada = str(payload.get("hora_entrada") or "").strip() or _now_hhmm()
    foto = str(payload.get("foto") or "").strip() or None
    qr_token = str(payload.get("qr_token") or "").strip() or None
    observaciones = str(payload.get("observaciones") or "").strip() or None
    lat = _parse_float(payload.get("lat"), "Latitud")
    lon = _parse_float(payload.get("lon"), "Longitud")
    _validate_geo(lat, lon)

    if metodo not in {"qr", "manual", "facial"}:
        return jsonify({"error": "metodo invalido"}), 400

    try:
        _parse_date(fecha)
        hora_entrada = _parse_hhmm(hora_entrada)
        _check_config_metodo(empleado["empresa_id"], metodo, lat, lon, foto)
        if metodo == "qr":
            _validar_qr_fichada(empleado, qr_token, "ingreso")
        _, estado_calc = validar_asistencia(empleado["id"], fecha, hora_entrada, None)
        estado = estado_calc or "ok"
        asistencia_id = register_entrada(
            empleado_id=empleado["id"],
            fecha=fecha,
            hora_entrada=hora_entrada,
            metodo_entrada=metodo,
            lat_entrada=lat,
            lon_entrada=lon,
            foto_entrada=foto,
            estado=estado,
            observaciones=observaciones,
        )
        return jsonify({"id": asistencia_id, "estado": estado}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@mobile_v1_bp.route("/me/fichadas/salida", methods=["POST"])
@mobile_auth_required
def fichar_salida():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    fecha = (payload.get("fecha") or "").strip() or _today_iso()
    metodo = str(payload.get("metodo") or "").strip().lower()
    hora_salida = str(payload.get("hora_salida") or "").strip() or _now_hhmm()
    hora_entrada = str(payload.get("hora_entrada") or "").strip() or None
    foto = str(payload.get("foto") or "").strip() or None
    qr_token = str(payload.get("qr_token") or "").strip() or None
    observaciones = str(payload.get("observaciones") or "").strip() or None
    lat = _parse_float(payload.get("lat"), "Latitud")
    lon = _parse_float(payload.get("lon"), "Longitud")
    _validate_geo(lat, lon)

    if metodo not in {"qr", "manual", "facial"}:
        return jsonify({"error": "metodo invalido"}), 400

    try:
        _parse_date(fecha)
        hora_salida = _parse_hhmm(hora_salida)
        if hora_entrada:
            hora_entrada = _parse_hhmm(hora_entrada)
        _check_config_metodo(empleado["empresa_id"], metodo, lat, lon, foto)
        if metodo == "qr":
            _validar_qr_fichada(empleado, qr_token, "egreso")
        _, estado_calc = validar_asistencia(empleado["id"], fecha, hora_entrada, hora_salida)
        estado = estado_calc or "ok"
        asistencia_id = register_salida(
            empleado_id=empleado["id"],
            fecha=fecha,
            hora_salida=hora_salida,
            metodo_salida=metodo,
            lat_salida=lat,
            lon_salida=lon,
            foto_salida=foto,
            estado=estado,
            observaciones=observaciones,
        )
        return jsonify({"id": asistencia_id, "estado": estado})
    except ValueError as exc:
        message = str(exc)
        code = 409 if "ya registrada" in message else 400
        if "No hay fichada de entrada" in message:
            code = 404
        return jsonify({"error": message}), code


@mobile_v1_bp.route("/me/perfil", methods=["PUT"])
@mobile_auth_required
def me_update_profile():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    telefono = str(payload.get("telefono") or empleado.get("telefono") or "").strip() or None
    direccion = str(payload.get("direccion") or empleado.get("direccion") or "").strip() or None
    foto = str(payload.get("foto") or empleado.get("foto") or "").strip() or None
    update_mobile_profile(empleado["id"], telefono=telefono, direccion=direccion, foto=foto)
    refreshed = get_empleado_by_id(empleado["id"])
    return jsonify(
        {
            "id": refreshed["id"],
            "telefono": refreshed.get("telefono"),
            "direccion": refreshed.get("direccion"),
            "foto": refreshed.get("foto"),
        }
    )


@mobile_v1_bp.route("/me/password", methods=["PUT"])
@mobile_auth_required
def me_update_password():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("password_actual") or "").strip()
    new_password = str(payload.get("password_nueva") or "").strip()
    if not current_password or not new_password:
        return jsonify({"error": "password_actual y password_nueva son requeridos"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "password_nueva debe tener al menos 8 caracteres"}), 400

    stored_hash = empleado.get("password_hash")
    if not stored_hash or not check_password_hash(stored_hash, current_password):
        return jsonify({"error": "password_actual incorrecta"}), 401

    update_empleado_password(empleado["id"], generate_password_hash(new_password))
    return jsonify({"ok": True})
