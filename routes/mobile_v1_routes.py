import datetime
import math
import re

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from repositories.auditoria_repository import create as create_audit
from repositories.asistencia_repository import (
    get_by_empleado_fecha,
    get_page_by_empleado as get_asistencias_page_by_empleado,
    upsert_resumen_desde_marca,
)
from repositories.asistencia_marca_repository import (
    count_by_empleado_fecha as count_marcas_by_empleado_fecha,
    create as create_asistencia_marca,
    get_last_by_empleado_fecha as get_last_marca_by_empleado_fecha,
    get_page_by_empleado as get_marcas_page_by_empleado,
)
from repositories.configuracion_empresa_repository import get_by_empresa_id
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.empleado_repository import (
    update_mobile_profile,
    update_password as update_empleado_password,
)
from repositories.mobile_stats_repository import get_by_empleado as get_mobile_stats_by_empleado
from repositories.security_event_repository import (
    create_geo_qr_rechazo,
    get_page_by_empleado as get_security_events_page,
)
from repositories.sucursal_repository import get_by_id as get_sucursal_by_id
from services.auth_service import authenticate_user
from services.profile_photo_service import delete_profile_photo_for_dni, upload_profile_photo
from utils.asistencia import get_horario_esperado, validar_asistencia
from utils.jwt import generar_token, generar_token_qr, verificar_token_qr
from utils.jwt_guard import mobile_auth_required
from utils.qr import build_qr_png_base64

mobile_v1_bp = Blueprint("mobile_v1", __name__, url_prefix="/api/v1/mobile")
TIPO_MARCA_VALUES = {"jornada", "desayuno", "almuerzo", "merienda", "otro"}


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


def _parse_bool(value, label: str, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "t", "yes", "y", "si", "sí", "on"}:
        return True
    if raw in {"0", "false", "f", "no", "off", ""}:
        return False
    raise ValueError(f"{label} invalido. Use true/false.")


def _parse_tipo_marca(value, *, default=None):
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw not in TIPO_MARCA_VALUES:
        raise ValueError("tipo_marca invalido. Use jornada, desayuno, almuerzo, merienda u otro.")
    return raw


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
        if metodo == "qr" and (lat is None or lon is None):
            raise ValueError("La posicion GPS es obligatoria para fichar por QR.")
        return {}

    if config.get("requiere_qr") and metodo != "qr":
        raise ValueError("La empresa requiere metodo QR.")
    if metodo == "qr" and (lat is None or lon is None):
        raise ValueError("La posicion GPS es obligatoria para fichar por QR.")
    if config.get("requiere_foto") and not foto:
        raise ValueError("La empresa requiere foto para fichar.")
    if config.get("requiere_geo") and (lat is None or lon is None):
        raise ValueError("La empresa requiere geolocalizacion para fichar.")
    return config


def _get_scan_cooldown_segundos(config: dict | None):
    if not config:
        return 60
    raw = config.get("cooldown_scan_segundos")
    if raw is None:
        return 60
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 60


def _parse_db_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _validar_cooldown_scan(ultima_marca: dict | None, cooldown_segundos: int):
    if not ultima_marca or cooldown_segundos <= 0:
        return

    last_dt = _parse_db_datetime(ultima_marca.get("fecha_creacion"))
    if last_dt is None:
        return

    now = datetime.datetime.now()
    elapsed = (now - last_dt).total_seconds()
    if elapsed < 0:
        return
    if elapsed < cooldown_segundos:
        restante = int(math.ceil(cooldown_segundos - elapsed))
        raise ValueError(f"Escaneo duplicado detectado. Espere {restante} segundos para volver a fichar.")


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


def _safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _registrar_intento_fraude_geo(
    *,
    empleado: dict,
    qr_payload: dict,
    geo: dict,
    fecha: str,
    hora: str | None,
    lat: float | None,
    lon: float | None,
):
    payload = {
        "empleado_id": empleado.get("id"),
        "empresa_id": empleado.get("empresa_id"),
        "fecha": fecha,
        "hora": hora,
        "lat": lat,
        "lon": lon,
        "ref_lat": geo.get("ref_lat"),
        "ref_lon": geo.get("ref_lon"),
        "distancia_m": geo.get("distancia_m"),
        "tolerancia_m": geo.get("tolerancia_m"),
        "sucursal_id": geo.get("sucursal_id"),
        "qr_accion": qr_payload.get("accion"),
        "qr_scope": qr_payload.get("scope"),
        "qr_empresa_id": qr_payload.get("empresa_id"),
    }
    try:
        evento_id = create_geo_qr_rechazo(
            empleado_id=int(empleado["id"]),
            empresa_id=int(empleado["empresa_id"]),
            fecha_operacion=fecha,
            hora_operacion=hora,
            lat=lat,
            lon=lon,
            ref_lat=geo.get("ref_lat"),
            ref_lon=geo.get("ref_lon"),
            distancia_m=geo.get("distancia_m"),
            tolerancia_m=geo.get("tolerancia_m"),
            sucursal_id=_safe_int(geo.get("sucursal_id")),
            qr_accion=str(qr_payload.get("accion") or "").strip().lower() or None,
            qr_scope=str(qr_payload.get("scope") or "").strip().lower() or None,
            qr_empresa_id=_safe_int(qr_payload.get("empresa_id")),
            payload=payload,
        )
    except Exception:
        current_app.logger.exception(
            "scan_qr_geo_rechazado_evento_error",
            extra={"extra": payload},
        )
        return None

    try:
        create_audit(None, "fraude_geo_qr_rechazado", "eventos_seguridad", evento_id)
    except Exception:
        current_app.logger.exception(
            "scan_qr_geo_rechazado_auditoria_error",
            extra={"extra": {"evento_id": evento_id}},
        )
    return evento_id


def _decidir_accion_scan(accion_qr: str, resumen: dict | None, ultima_marca: dict | None):
    if accion_qr in {"ingreso", "egreso"}:
        accion = accion_qr
    elif ultima_marca:
        accion = "egreso" if str(ultima_marca.get("accion")) == "ingreso" else "ingreso"
    elif not resumen or resumen.get("hora_entrada") is None:
        accion = "ingreso"
    elif resumen.get("hora_salida") is None:
        accion = "egreso"
    else:
        # Si no hay marcas atomicas y el resumen del dia esta cerrado, asumimos nuevo ciclo.
        accion = "ingreso"

    if ultima_marca:
        ultima_accion = str(ultima_marca.get("accion") or "").strip().lower()
        if ultima_accion == accion:
            raise ValueError(f"Secuencia invalida de marcas. Ultima accion: {ultima_accion}.")
        if accion == "egreso" and ultima_accion != "ingreso":
            raise ValueError("No hay fichada de entrada para esa fecha.")
        return accion

    if accion == "egreso" and (not resumen or resumen.get("hora_entrada") is None):
        raise ValueError("No hay fichada de entrada para esa fecha.")
    if (
        accion == "ingreso"
        and resumen
        and resumen.get("hora_entrada") is not None
        and resumen.get("hora_salida") is None
    ):
        raise ValueError("Ya hay un ingreso abierto para esa fecha.")
    return accion


def _hora_entrada_para_egreso(resumen: dict | None, ultima_marca: dict | None):
    if ultima_marca and str(ultima_marca.get("accion")) == "ingreso":
        return _to_hhmm(ultima_marca.get("hora"))
    if resumen:
        return _to_hhmm(resumen.get("hora_entrada"))
    return None


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
                "foto": user.get("foto"),
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
            "cooldown_scan_segundos": _get_scan_cooldown_segundos(config),
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
        tipo_marca = _parse_tipo_marca(payload.get("tipo_marca"), default="jornada")

        qr_payload = {
            "accion": accion,
            "empresa_id": empleado["empresa_id"],
            "scope": scope,
            "tipo_marca": tipo_marca,
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
                "tipo_marca": tipo_marca,
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
    tipo_marca_raw = payload.get("tipo_marca")
    lat = _parse_float(payload.get("lat"), "Latitud")
    lon = _parse_float(payload.get("lon"), "Longitud")
    _validate_geo(lat, lon)

    try:
        _parse_date(fecha)
        hora = _parse_hhmm(hora)
        tipo_marca_input = _parse_tipo_marca(tipo_marca_raw, default=None)
        config_empresa = _check_config_metodo(empleado["empresa_id"], "qr", lat, lon, foto)
        qr_payload = _validar_qr_fichada(empleado, qr_token, None)
        tipo_marca_qr = _parse_tipo_marca(qr_payload.get("tipo_marca"), default=None)
        tipo_marca = tipo_marca_qr or tipo_marca_input or "jornada"
        geo = _validar_geo_scan_qr(empleado, qr_payload, lat, lon)
        if not geo["gps_ok"]:
            evento_id = _registrar_intento_fraude_geo(
                empleado=empleado,
                qr_payload=qr_payload,
                geo=geo,
                fecha=fecha,
                hora=hora,
                lat=lat,
                lon=lon,
            )
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
                        "evento_id": evento_id,
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
                        "alerta_fraude": True,
                        "evento_id": evento_id,
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
        resumen = get_by_empleado_fecha(empleado["id"], fecha)
        ultima_marca = get_last_marca_by_empleado_fecha(empleado["id"], fecha)
        cooldown_scan = _get_scan_cooldown_segundos(config_empresa)
        _validar_cooldown_scan(ultima_marca, cooldown_scan)
        accion = _decidir_accion_scan(accion_qr, resumen, ultima_marca)

        if accion == "ingreso":
            _, estado_calc = validar_asistencia(empleado["id"], fecha, hora, None)
            estado = estado_calc or "ok"
            asistencia_id = upsert_resumen_desde_marca(
                empleado_id=empleado["id"],
                fecha=fecha,
                hora=hora,
                accion="ingreso",
                metodo="qr",
                lat=lat,
                lon=lon,
                foto=foto,
                estado=estado,
                observaciones=observaciones,
                gps_ok=True,
                gps_distancia_m=geo["distancia_m"],
                gps_tolerancia_m=geo["tolerancia_m"],
                gps_ref_lat=geo["ref_lat"],
                gps_ref_lon=geo["ref_lon"],
            )
        else:
            hora_entrada = _hora_entrada_para_egreso(resumen, ultima_marca)
            _, estado_calc = validar_asistencia(empleado["id"], fecha, hora_entrada, hora)
            estado = estado_calc or "ok"
            asistencia_id = upsert_resumen_desde_marca(
                empleado_id=empleado["id"],
                fecha=fecha,
                hora=hora,
                accion="egreso",
                metodo="qr",
                lat=lat,
                lon=lon,
                foto=foto,
                estado=estado,
                observaciones=observaciones,
                gps_ok=True,
                gps_distancia_m=geo["distancia_m"],
                gps_tolerancia_m=geo["tolerancia_m"],
                gps_ref_lat=geo["ref_lat"],
                gps_ref_lon=geo["ref_lon"],
            )

        marca_id = create_asistencia_marca(
            empresa_id=int(empleado["empresa_id"]),
            empleado_id=empleado["id"],
            asistencia_id=asistencia_id,
            fecha=fecha,
            hora=hora,
            accion=accion,
            metodo="qr",
            tipo_marca=tipo_marca,
            lat=lat,
            lon=lon,
            foto=foto,
            gps_ok=True,
            gps_distancia_m=geo["distancia_m"],
            gps_tolerancia_m=geo["tolerancia_m"],
            gps_ref_lat=geo["ref_lat"],
            gps_ref_lon=geo["ref_lon"],
            estado=estado,
            observaciones=observaciones,
        )
        total_marcas = count_marcas_by_empleado_fecha(empleado["id"], fecha)
        body = {
            "id": asistencia_id,
            "marca_id": marca_id,
            "accion": accion,
            "tipo_marca": tipo_marca,
            "estado": estado,
            "gps_ok": True,
            "distancia_m": geo["distancia_m"],
            "tolerancia_m": geo["tolerancia_m"],
            "total_marcas_dia": total_marcas,
        }
        status = 201 if accion == "ingreso" else 200
        return (
            jsonify(body),
            status,
        )
    except ValueError as exc:
        message = str(exc)
        lowered = message.lower()
        if "escaneo duplicado detectado" in lowered:
            remaining = None
            match = re.search(r"(\d+)", message)
            if match:
                try:
                    remaining = int(match.group(1))
                except ValueError:
                    remaining = None
            return (
                jsonify(
                    {
                        "error": message,
                        "code": "scan_cooldown",
                        "cooldown_segundos_restantes": remaining,
                    }
                ),
                409,
            )
        code = 400
        if (
            "secuencia invalida" in lowered
            or "ya registrada" in lowered
            or "ya hay un ingreso abierto" in lowered
            or "ya existe entrada y salida" in lowered
            or "duplicado" in lowered
        ):
            code = 409
        if "no hay fichada de entrada" in lowered:
            code = 404
        return jsonify({"error": message}), code


@mobile_v1_bp.route("/me/marcas", methods=["GET"])
@mobile_auth_required
def me_marcas():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = request.args.get("page", 1, type=int) or 1
    page = max(1, page)
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

    rows, total = get_marcas_page_by_empleado(
        empleado_id=empleado["id"],
        page=page,
        per_page=per_page,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "asistencia_id": row.get("asistencia_id"),
                "fecha": _to_date_str(row.get("fecha")),
                "hora": _to_hhmm(row.get("hora")),
                "accion": row.get("accion"),
                "metodo": row.get("metodo"),
                "tipo_marca": row.get("tipo_marca") or "jornada",
                "estado": row.get("estado"),
                "observaciones": row.get("observaciones"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "gps_ok": bool(row.get("gps_ok")) if row.get("gps_ok") is not None else None,
                "gps_distancia_m": row.get("gps_distancia_m"),
                "gps_tolerancia_m": row.get("gps_tolerancia_m"),
                "fecha_creacion": _to_date_str(row.get("fecha_creacion")) if row.get("fecha_creacion") else None,
            }
        )
    return jsonify(
        {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total": total,
        }
    )


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
    page = max(1, page)
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

    rows, total = get_asistencias_page_by_empleado(
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


@mobile_v1_bp.route("/me/estadisticas", methods=["GET"])
@mobile_auth_required
def me_estadisticas():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    today_dt = datetime.date.today()
    today_iso = today_dt.isoformat()
    fecha_desde = (request.args.get("desde") or "").strip() or (today_dt - datetime.timedelta(days=29)).isoformat()
    fecha_hasta = (request.args.get("hasta") or "").strip() or today_iso

    try:
        _parse_date(fecha_desde)
        _parse_date(fecha_hasta)
        desde_dt = datetime.date.fromisoformat(fecha_desde)
        hasta_dt = datetime.date.fromisoformat(fecha_hasta)
    except ValueError:
        return jsonify({"error": "Rango de fechas invalido"}), 400

    if desde_dt > hasta_dt:
        return jsonify({"error": "El rango de fechas es invalido (desde > hasta)."}), 400
    if desde_dt > today_dt or hasta_dt > today_dt:
        return jsonify({"error": "No se permiten fechas futuras en estadisticas."}), 400
    if (hasta_dt - desde_dt).days > 366:
        return jsonify({"error": "El rango maximo permitido es 366 dias."}), 400

    try:
        data = get_mobile_stats_by_empleado(
            empleado_id=int(empleado["id"]),
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except Exception:
        current_app.logger.exception(
            "mobile_estadisticas_error",
            extra={
                "extra": {
                    "empleado_id": empleado.get("id"),
                    "empresa_id": empleado.get("empresa_id"),
                    "desde": fecha_desde,
                    "hasta": fecha_hasta,
                }
            },
        )
        return jsonify({"error": "No se pudieron obtener estadisticas."}), 500

    return jsonify(
        {
            "periodo": {
                "desde": fecha_desde,
                "hasta": fecha_hasta,
                "dias": (hasta_dt - desde_dt).days + 1,
            },
            **(data or {}),
        }
    )


@mobile_v1_bp.route("/me/eventos-seguridad", methods=["GET"])
@mobile_auth_required
def me_eventos_seguridad():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = request.args.get("page", 1, type=int) or 1
    page = max(1, page)
    per_page = request.args.get("per", 20, type=int) or 20
    per_page = max(1, min(per_page, 100))
    tipo_evento = (request.args.get("tipo_evento") or "").strip() or None

    try:
        rows, total = get_security_events_page(
            empleado_id=int(empleado["id"]),
            page=page,
            per_page=per_page,
            tipo_evento=tipo_evento,
        )
    except Exception:
        current_app.logger.exception(
            "mobile_eventos_seguridad_error",
            extra={
                "extra": {
                    "empleado_id": empleado.get("id"),
                    "empresa_id": empleado.get("empresa_id"),
                    "page": page,
                    "per_page": per_page,
                    "tipo_evento": tipo_evento,
                }
            },
        )
        return jsonify({"error": "No se pudo obtener eventos de seguridad."}), 500
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "tipo_evento": row.get("tipo_evento"),
                "severidad": row.get("severidad"),
                "alerta_fraude": bool(row.get("alerta_fraude")),
                "fecha": _to_date_str(row.get("fecha")),
                "fecha_operacion": _to_date_str(row.get("fecha_operacion")) if row.get("fecha_operacion") else None,
                "hora_operacion": _to_hhmm(row.get("hora_operacion")),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "ref_lat": row.get("ref_lat"),
                "ref_lon": row.get("ref_lon"),
                "distancia_m": row.get("distancia_m"),
                "tolerancia_m": row.get("tolerancia_m"),
                "sucursal_id": row.get("sucursal_id"),
            }
        )
    return jsonify(
        {
            "items": items,
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
    tipo_marca_raw = payload.get("tipo_marca")
    lat = _parse_float(payload.get("lat"), "Latitud")
    lon = _parse_float(payload.get("lon"), "Longitud")
    _validate_geo(lat, lon)

    if metodo not in {"qr", "manual", "facial"}:
        return jsonify({"error": "metodo invalido"}), 400

    try:
        _parse_date(fecha)
        hora_entrada = _parse_hhmm(hora_entrada)
        tipo_marca = _parse_tipo_marca(tipo_marca_raw, default="jornada")
        _check_config_metodo(empleado["empresa_id"], metodo, lat, lon, foto)
        if metodo == "qr":
            _validar_qr_fichada(empleado, qr_token, "ingreso")
        resumen = get_by_empleado_fecha(empleado["id"], fecha)
        ultima_marca = get_last_marca_by_empleado_fecha(empleado["id"], fecha)
        _decidir_accion_scan("ingreso", resumen, ultima_marca)
        _, estado_calc = validar_asistencia(empleado["id"], fecha, hora_entrada, None)
        estado = estado_calc or "ok"
        asistencia_id = upsert_resumen_desde_marca(
            empleado_id=empleado["id"],
            fecha=fecha,
            hora=hora_entrada,
            accion="ingreso",
            metodo=metodo,
            lat=lat,
            lon=lon,
            foto=foto,
            estado=estado,
            observaciones=observaciones,
            gps_ok=None,
            gps_distancia_m=None,
            gps_tolerancia_m=None,
            gps_ref_lat=None,
            gps_ref_lon=None,
        )
        marca_id = create_asistencia_marca(
            empresa_id=int(empleado["empresa_id"]),
            empleado_id=empleado["id"],
            asistencia_id=asistencia_id,
            fecha=fecha,
            hora=hora_entrada,
            accion="ingreso",
            metodo=metodo,
            tipo_marca=tipo_marca,
            lat=lat,
            lon=lon,
            foto=foto,
            gps_ok=None,
            gps_distancia_m=None,
            gps_tolerancia_m=None,
            gps_ref_lat=None,
            gps_ref_lon=None,
            estado=estado,
            observaciones=observaciones,
        )
        return jsonify({"id": asistencia_id, "marca_id": marca_id, "estado": estado}), 201
    except ValueError as exc:
        message = str(exc)
        lowered = message.lower()
        code = 400
        if (
            "secuencia invalida" in lowered
            or "ya registrada" in lowered
            or "ya hay un ingreso abierto" in lowered
            or "duplicado" in lowered
        ):
            code = 409
        if "no hay fichada de entrada" in lowered:
            code = 404
        return jsonify({"error": message}), code


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
    tipo_marca_raw = payload.get("tipo_marca")
    lat = _parse_float(payload.get("lat"), "Latitud")
    lon = _parse_float(payload.get("lon"), "Longitud")
    _validate_geo(lat, lon)

    if metodo not in {"qr", "manual", "facial"}:
        return jsonify({"error": "metodo invalido"}), 400

    try:
        _parse_date(fecha)
        hora_salida = _parse_hhmm(hora_salida)
        tipo_marca = _parse_tipo_marca(tipo_marca_raw, default="jornada")
        if hora_entrada:
            hora_entrada = _parse_hhmm(hora_entrada)
        _check_config_metodo(empleado["empresa_id"], metodo, lat, lon, foto)
        if metodo == "qr":
            _validar_qr_fichada(empleado, qr_token, "egreso")
        resumen = get_by_empleado_fecha(empleado["id"], fecha)
        ultima_marca = get_last_marca_by_empleado_fecha(empleado["id"], fecha)
        _decidir_accion_scan("egreso", resumen, ultima_marca)
        hora_entrada_base = hora_entrada or _hora_entrada_para_egreso(resumen, ultima_marca)
        if not hora_entrada_base and resumen:
            hora_entrada_base = _to_hhmm(resumen.get("hora_entrada"))
        _, estado_calc = validar_asistencia(empleado["id"], fecha, hora_entrada_base, hora_salida)
        estado = estado_calc or "ok"
        asistencia_id = upsert_resumen_desde_marca(
            empleado_id=empleado["id"],
            fecha=fecha,
            hora=hora_salida,
            accion="egreso",
            metodo=metodo,
            lat=lat,
            lon=lon,
            foto=foto,
            estado=estado,
            observaciones=observaciones,
            gps_ok=None,
            gps_distancia_m=None,
            gps_tolerancia_m=None,
            gps_ref_lat=None,
            gps_ref_lon=None,
        )
        marca_id = create_asistencia_marca(
            empresa_id=int(empleado["empresa_id"]),
            empleado_id=empleado["id"],
            asistencia_id=asistencia_id,
            fecha=fecha,
            hora=hora_salida,
            accion="egreso",
            metodo=metodo,
            tipo_marca=tipo_marca,
            lat=lat,
            lon=lon,
            foto=foto,
            gps_ok=None,
            gps_distancia_m=None,
            gps_tolerancia_m=None,
            gps_ref_lat=None,
            gps_ref_lon=None,
            estado=estado,
            observaciones=observaciones,
        )
        return jsonify({"id": asistencia_id, "marca_id": marca_id, "estado": estado})
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
    form_data = request.form or {}

    has_telefono = "telefono" in payload or "telefono" in form_data
    has_direccion = "direccion" in payload or "direccion" in form_data
    has_foto = "foto" in payload or "foto" in form_data

    telefono_raw = payload["telefono"] if "telefono" in payload else form_data.get("telefono")
    direccion_raw = payload["direccion"] if "direccion" in payload else form_data.get("direccion")
    foto_raw = payload["foto"] if "foto" in payload else form_data.get("foto")
    eliminar_foto_raw = (
        payload["eliminar_foto"] if "eliminar_foto" in payload else form_data.get("eliminar_foto")
    )
    try:
        eliminar_foto = _parse_bool(eliminar_foto_raw, "eliminar_foto", default=False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    telefono_base = telefono_raw if has_telefono else empleado.get("telefono")
    direccion_base = direccion_raw if has_direccion else empleado.get("direccion")
    foto_base = foto_raw if has_foto else empleado.get("foto")

    telefono = str(telefono_base or "").strip() or None
    direccion = str(direccion_base or "").strip() or None
    foto = str(foto_base or "").strip() or None

    foto_file = request.files.get("foto_file") or request.files.get("foto")
    if foto_file and str(foto_file.filename or "").strip() and eliminar_foto:
        return jsonify({"error": "No puede enviar foto_file junto con eliminar_foto=true."}), 400

    if foto_file and str(foto_file.filename or "").strip():
        try:
            foto = upload_profile_photo(foto_file, empleado.get("dni"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError:
            current_app.logger.exception(
                "mobile_profile_photo_upload_error",
                extra={
                    "extra": {
                        "empleado_id": empleado.get("id"),
                        "empresa_id": empleado.get("empresa_id"),
                        "dni": empleado.get("dni"),
                    }
                },
            )
            return jsonify({"error": "No se pudo subir la foto de perfil."}), 500
    elif eliminar_foto or (has_foto and foto is None):
        foto = None
        try:
            delete_profile_photo_for_dni(empleado.get("dni"))
        except ValueError:
            # Sin config FTP: limpiamos foto en DB igual para no bloquear al empleado.
            pass
        except RuntimeError:
            current_app.logger.warning(
                "mobile_profile_photo_delete_ftp_error",
                extra={
                    "extra": {
                        "empleado_id": empleado.get("id"),
                        "empresa_id": empleado.get("empresa_id"),
                        "dni": empleado.get("dni"),
                    }
                },
            )

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


@mobile_v1_bp.route("/me/perfil/foto", methods=["DELETE"])
@mobile_auth_required
def me_delete_profile_photo():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    try:
        delete_profile_photo_for_dni(empleado.get("dni"))
    except ValueError:
        # Sin configuracion FTP: permitimos baja logica de foto en DB.
        pass
    except RuntimeError:
        current_app.logger.warning(
            "mobile_profile_photo_delete_ftp_error",
            extra={
                "extra": {
                    "empleado_id": empleado.get("id"),
                    "empresa_id": empleado.get("empresa_id"),
                    "dni": empleado.get("dni"),
                }
            },
        )

    update_mobile_profile(
        empleado["id"],
        telefono=str(empleado.get("telefono") or "").strip() or None,
        direccion=str(empleado.get("direccion") or "").strip() or None,
        foto=None,
    )
    return jsonify({"ok": True, "foto": None})


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
