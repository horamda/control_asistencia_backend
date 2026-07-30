import datetime
import re

from flask import Blueprint, Response, current_app, g, jsonify, request, send_file
from werkzeug.security import check_password_hash, generate_password_hash

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
    get_page as get_empleados_page,
    update_mobile_profile,
    update_password as update_empleado_password,
)
from repositories.legajo_evento_repository import (
    create_evento,
    get_tipo_evento_by_id,
    get_tipos_evento,
    get_eventos_page,
    get_evento_by_id_for_empleado,
    get_conteo_por_tipo_for_empleado,
)
from repositories.legajo_adjunto_repository import (
    create_adjunto,
    get_adjunto_by_id,
    get_adjunto_by_id_for_empleado,
    get_adjunto_data_by_id,
    get_adjuntos_by_evento_for_empleado,
)
from repositories.mobile_legajo_permiso_repository import (
    PERMISO_CARGAR_EVENTOS_LEGAJO,
    alcance_permiso as get_mobile_legajo_alcance,
)
from repositories.franco_repository import (
    get_page_by_empleado as get_francos_page_by_empleado,
    get_by_id as get_franco_by_id,
)
from repositories.empleado_horario_repository import (
    get_actual_by_empleado as get_horario_actual_by_empleado,
    get_historial as get_horario_historial_by_empleado,
)
from repositories.horario_dia_repository import get_by_horario as get_dias_by_horario
from repositories.adelanto_repository import (
    get_by_id as get_adelanto_by_id,
    get_page_by_empleado as get_adelantos_page_by_empleado,
)
from repositories.articulo_catalogo_pedido_repository import (
    get_page as get_articulos_catalogo_pedidos_page,
)
from repositories.vacacion_repository import (
    get_page_by_empleado as get_vacaciones_page_by_empleado,
)
from repositories.justificacion_repository import (
    marcar_vista_por_empleado as marcar_justificacion_vista_por_empleado,
    get_by_id as get_justificacion_by_id,
    get_page as get_justificaciones_page,
    delete as delete_justificacion_row,
)
from services.adelanto_service import (
    AdelantoAlreadyRequestedError,
    get_adelanto_mes_actual as get_adelanto_mes_actual_svc,
    solicitar_adelanto as solicitar_adelanto_svc,
)
from services.pedido_mercaderia_service import (
    PedidoMercaderiaAlreadyRequestedError,
    cancelar_pedido as cancelar_pedido_mercaderia_svc,
    editar_pedido as editar_pedido_mercaderia_svc,
    get_pedido_mes_actual as get_pedido_mercaderia_mes_actual_svc,
    solicitar_pedido as solicitar_pedido_mercaderia_svc,
)
from services.justificacion_service import (
    create_justificacion as create_justificacion_svc,
    update_justificacion as update_justificacion_svc,
)
from services.justificacion_attachment_service import (
    MAX_JUSTIFICACION_ADJUNTOS,
    delete_justificacion_adjunto,
    delete_justificacion_resources,
    justificacion_adjunto_to_mobile_dict,
    list_justificacion_adjuntos,
    save_justificacion_adjuntos,
    sync_justificacion_event,
)
from services.vacaciones_service import (
    VacacionesError,
    VacacionesSaldoInsuficienteError,
    cancelar_movimiento_vacaciones,
    calcular_resumen_vacaciones,
    editar_movimiento_vacaciones_pendiente,
    listar_movimientos_vacaciones,
    rechazar_movimiento_vacaciones,
    solicitar_vacaciones as solicitar_vacaciones_svc,
)
from repositories.vacaciones_repository import get_movimiento_by_id as get_vacaciones_movimiento_by_id
from services.legajo_attachment_service import resolve_legajo_storage_path, save_legajo_attachment_local
from services.legajo_service import (
    calcular_resumen_legajo,
    legajo_evento_to_mobile_dict,
    legajo_tipo_evento_to_mobile_dict,
)
from repositories.pedido_mercaderia_repository import (
    get_by_id as get_pedido_mercaderia_by_id,
    get_page_by_empleado as get_pedidos_mercaderia_page_by_empleado,
)
from repositories.mobile_stats_repository import get_by_empleado as get_mobile_stats_by_empleado
from repositories.premio_concurso_repository import (
    MONTH_NAMES as PREMIO_MONTH_NAMES,
    get_resultados_empleado_anio as get_premios_resultados_empleado_anio,
)
from repositories.qr_puerta_repository import get_by_token as get_qr_puerta_by_token
from repositories.auditoria_repository import create as create_audit
from repositories.app_version_repository import get_version_config
from repositories.security_event_repository import (
    create_geo_qr_rechazo,
    get_page_by_empleado as get_security_events_page,
)
from services.auth_service import authenticate_user
from services.auth_service import AUTH_INVALID_CREDENTIALS_MESSAGE
from services.profile_photo_service import (
    delete_profile_photo_for_dni,
    get_profile_photo_version_by_dni,
    upload_profile_photo,
)
from utils.asistencia import get_horario_esperado, validar_asistencia
from utils.jwt import (
    DEFAULT_QR_TTL_SECONDS,
    QRTokenValidationError,
    extract_qr_token,
    generar_token,
    generar_token_qr,
    verificar_token_qr,
)
from utils.jwt_guard import INVALID_SESSION_MESSAGE, mobile_auth_required
from utils.qr import build_qr_png_base64
from routes.mobile_v1_helpers import (
    DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN,
    TIPO_MARCA_VALUES,
    _decidir_accion_scan,
    _get_intervalo_minimo_fichadas_min,
    _get_scan_cooldown_segundos,
    _geo_ref_from_qr_payload,
    _haversine_m,
    _hora_entrada_para_egreso,
    _now_hhmm,
    _parse_bool,
    _parse_date,
    _parse_float,
    _parse_hhmm,
    _parse_int,
    _parse_tipo_marca,
    _safe_int,
    _to_date_str,
    _to_hhmm,
    _today_iso,
    _validate_geo,
    _validar_cooldown_scan,
    _validar_intervalo_minimo_marcas,
)

mobile_v1_bp = Blueprint("mobile_v1", __name__, url_prefix="/api/v1/mobile")


# ---------------------------------------------------------------------------
# Helpers con acceso a repositorios/servicios
# (permanecen aquí para que los tests puedan hacer monkeypatch sobre este módulo)
# ---------------------------------------------------------------------------

def _api_error_body(message: str, exc: Exception | None = None) -> dict:
    body = {"error": message}
    code = getattr(exc, "code", None)
    if code:
        body["code"] = code
    return body


def _mobile_user():
    empleado_id = int(g.mobile_empleado_id)
    empleado = get_empleado_by_id(empleado_id)
    if not empleado or not empleado.get("activo"):
        return None
    return empleado


def _imagen_version_for_dni(dni):
    try:
        return get_profile_photo_version_by_dni(dni)
    except Exception:
        current_app.logger.warning(
            "mobile_profile_image_version_error",
            extra={"extra": {"dni": dni}},
        )
        return None


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


def _geo_ref_from_empleado(empleado):
    sucursal_id = empleado.get("sucursal_id")
    if not sucursal_id:
        return None
    from repositories.sucursal_repository import get_by_id as get_sucursal_by_id
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
        raise QRTokenValidationError(
            "qr_token requerido para metodo qr.",
            "qr_token_required",
        )
    try:
        payload = verificar_token_qr(token, accion_esperada=accion)
        _validar_qr_puerta_activo(token, payload)
    except QRTokenValidationError as exc:
        current_app.logger.warning(
            "qr_fichada_validation_error",
            extra={
                "extra": {
                    "code": getattr(exc, "code", None),
                    "message": str(exc),
                    "empleado_id": empleado.get("id") if empleado else None,
                    "empresa_id": empleado.get("empresa_id") if empleado else None,
                }
            },
        )
        raise
    token_empresa = int(payload.get("empresa_id"))
    if token_empresa != int(empleado["empresa_id"]):
        raise QRTokenValidationError(
            "QR no corresponde a la empresa del empleado.",
            "qr_wrong_empresa",
            status_code=403,
        )
    token_empleado = payload.get("empleado_id")
    if token_empleado is not None and int(token_empleado) != int(empleado["id"]):
        raise QRTokenValidationError(
            "QR no corresponde al empleado autenticado.",
            "qr_wrong_empleado",
            status_code=403,
        )
    return payload


def _validar_qr_puerta_activo(qr_token: str, qr_payload: dict):
    if str(qr_payload.get("origen") or "").strip().lower() != "web_admin_puerta":
        return

    try:
        row = get_qr_puerta_by_token(extract_qr_token(qr_token))
    except QRTokenValidationError:
        raise
    except Exception as exc:
        current_app.logger.error(
            "qr_puerta_db_lookup_error",
            extra={"extra": {"error": str(exc), "exc_type": type(exc).__name__}},
            exc_info=True,
        )
        raise QRTokenValidationError(
            "Error al verificar QR. Contacte al administrador.",
            "qr_db_error",
            status_code=500,
        ) from exc
    if not row:
        raise QRTokenValidationError(
            "QR no registrado. Genere un QR nuevo desde el panel.",
            "qr_not_registered",
            status_code=403,
        )
    activo = row.get("activo")
    if activo is None:
        activo = 1
    try:
        activo_bool = bool(int(activo))
    except (TypeError, ValueError):
        activo_bool = bool(activo)
    if not activo_bool:
        raise QRTokenValidationError(
            "QR inactivo. Genere un QR nuevo desde el panel.",
            "qr_inactive",
            status_code=403,
        )


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
            "scan_qr_geo_fraude_evento_error",
            extra={"extra": payload},
        )
        return None
    try:
        create_audit(None, "fraude_geo_qr_detectado", "eventos_seguridad", evento_id)
    except Exception:
        current_app.logger.exception(
            "scan_qr_geo_fraude_auditoria_error",
            extra={"extra": {"evento_id": evento_id}},
        )
    return evento_id


@mobile_v1_bp.route("/version", methods=["GET"])
def app_version():
    platform = (request.args.get("platform") or "android").strip().lower()
    if platform not in ("android", "ios"):
        platform = "android"

    config = get_version_config(platform)
    if not config:
        return jsonify({
            "ok": True,
            "platform": platform,
            "version_minima": "1.0.0",
            "version_recomendada": "1.0.0",
            "url_descarga": None,
            "mensaje": None,
        })

    return jsonify({
        "ok": True,
        "platform": platform,
        "version_minima": config.get("version_minima") or "1.0.0",
        "version_recomendada": config.get("version_recomendada") or "1.0.0",
        "url_descarga": config.get("url_descarga"),
        "mensaje": config.get("mensaje"),
    })


def _client_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or None


@mobile_v1_bp.route("/auth/login", methods=["POST"])
def auth_login():
    from repositories.mobile_sesiones_repository import create_sesion

    payload = request.get_json(silent=True) or {}
    dni = str(payload.get("dni") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not dni or not password:
        return jsonify({"error": "dni y password son requeridos"}), 400

    user, error = authenticate_user(dni, password)
    if error:
        current_app.logger.info(
            "mobile_auth_login_failed",
            extra={"extra": {"dni": dni, "reason": error}},
        )
        return jsonify({"error": AUTH_INVALID_CREDENTIALS_MESSAGE}), 401

    try:
        sesion_id = create_sesion({
            "empleado_id": user["id"],
            "dni": user["dni"],
            "ip": _client_ip(),
            "platform": str(payload.get("platform") or "").strip().lower() or None,
            "device_model": str(payload.get("device_model") or "").strip() or None,
            "app_version": str(payload.get("app_version") or "").strip() or None,
        })
    except Exception:
        sesion_id = None

    token = generar_token(
        {
            "empleado_id": user["id"],
            "user_id": user["id"],
            "dni": user["dni"],
            "nombre": user["nombre"],
            "sesion_id": sesion_id,
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
                "imagen_version": _imagen_version_for_dni(user.get("dni")),
            },
        }
    )


@mobile_v1_bp.route("/auth/refresh", methods=["POST"])
@mobile_auth_required
def auth_refresh():
    from repositories.mobile_sesiones_repository import update_ultimo_request

    empleado = _mobile_user()
    if not empleado:
        current_app.logger.info("mobile_auth_refresh_failed", extra={"extra": {"reason": "inactive_or_missing"}})
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401

    sesion_id = g.mobile_payload.get("sesion_id") if hasattr(g, "mobile_payload") else None
    if sesion_id:
        try:
            update_ultimo_request(int(sesion_id))
        except Exception:
            pass

    token = generar_token(
        {
            "empleado_id": empleado["id"],
            "user_id": empleado["id"],
            "dni": empleado["dni"],
            "nombre": empleado["nombre"],
            "sesion_id": sesion_id,
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
            "imagen_version": _imagen_version_for_dni(empleado.get("dni")),
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
            "intervalo_minimo_fichadas_minutos": _get_intervalo_minimo_fichadas_min(config),
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
        vigencia_segundos = _parse_int(
            payload.get("vigencia_segundos"),
            "vigencia_segundos",
            DEFAULT_QR_TTL_SECONDS,
        )
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
        intervalo_minimo_fichadas = _get_intervalo_minimo_fichadas_min(config_empresa)
        qr_payload = _validar_qr_fichada(empleado, qr_token, None)
        tipo_marca_qr = _parse_tipo_marca(qr_payload.get("tipo_marca"), default=None)
        tipo_marca = tipo_marca_qr or tipo_marca_input or "jornada"
        geo = _validar_geo_scan_qr(empleado, qr_payload, lat, lon)
        gps_ok = bool(geo.get("gps_ok"))
        alerta_fraude = not gps_ok

        gps_note = (
            f"gps_ok={1 if gps_ok else 0};dist_m={geo['distancia_m']};tol_m={geo['tolerancia_m']};"
            f"ref={geo['ref_lat']},{geo['ref_lon']}"
        )
        if alerta_fraude:
            gps_note = f"{gps_note};alerta_fraude=1"
        observaciones = f"{observaciones} | {gps_note}" if observaciones else gps_note

        accion_qr = str(qr_payload.get("accion") or "auto").strip().lower()
        resumen = get_by_empleado_fecha(empleado["id"], fecha)
        ultima_marca = get_last_marca_by_empleado_fecha(empleado["id"], fecha)
        cooldown_scan = _get_scan_cooldown_segundos(config_empresa)
        _validar_cooldown_scan(ultima_marca, cooldown_scan)
        _validar_intervalo_minimo_marcas(ultima_marca, hora, intervalo_minimo_fichadas)
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
                gps_ok=gps_ok,
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
                gps_ok=gps_ok,
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
            gps_ok=gps_ok,
            gps_distancia_m=geo["distancia_m"],
            gps_tolerancia_m=geo["tolerancia_m"],
            gps_ref_lat=geo["ref_lat"],
            gps_ref_lon=geo["ref_lon"],
            estado=estado,
            observaciones=observaciones,
        )
        evento_id = None
        if alerta_fraude:
            evento_id = _registrar_intento_fraude_geo(
                empleado=empleado,
                qr_payload=qr_payload,
                geo=geo,
                fecha=fecha,
                hora=hora,
                lat=lat,
                lon=lon,
            )
            current_app.logger.warning(
                "scan_qr_geo_fuera_rango_permitido",
                extra={
                    "extra": {
                        "empleado_id": empleado["id"],
                        "empresa_id": empleado["empresa_id"],
                        "asistencia_id": asistencia_id,
                        "marca_id": marca_id,
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
        total_marcas = count_marcas_by_empleado_fecha(empleado["id"], fecha)
        body = {
            "id": asistencia_id,
            "marca_id": marca_id,
            "accion": accion,
            "tipo_marca": tipo_marca,
            "estado": estado,
            "gps_ok": gps_ok,
            "distancia_m": geo["distancia_m"],
            "tolerancia_m": geo["tolerancia_m"],
            "alerta_fraude": alerta_fraude,
            "evento_id": evento_id,
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
        code = getattr(exc, "status_code", 400) or 400
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
        return jsonify(_api_error_body(message, exc)), code


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
        config_empresa = _check_config_metodo(empleado["empresa_id"], metodo, lat, lon, foto)
        intervalo_minimo_fichadas = _get_intervalo_minimo_fichadas_min(config_empresa)
        if metodo == "qr":
            _validar_qr_fichada(empleado, qr_token, "ingreso")
        resumen = get_by_empleado_fecha(empleado["id"], fecha)
        ultima_marca = get_last_marca_by_empleado_fecha(empleado["id"], fecha)
        _validar_intervalo_minimo_marcas(ultima_marca, hora_entrada, intervalo_minimo_fichadas)
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
        code = getattr(exc, "status_code", 400) or 400
        if (
            "secuencia invalida" in lowered
            or "ya registrada" in lowered
            or "ya hay un ingreso abierto" in lowered
            or "duplicado" in lowered
        ):
            code = 409
        if "no hay fichada de entrada" in lowered:
            code = 404
        return jsonify(_api_error_body(message, exc)), code


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
        config_empresa = _check_config_metodo(empleado["empresa_id"], metodo, lat, lon, foto)
        intervalo_minimo_fichadas = _get_intervalo_minimo_fichadas_min(config_empresa)
        if metodo == "qr":
            _validar_qr_fichada(empleado, qr_token, "egreso")
        resumen = get_by_empleado_fecha(empleado["id"], fecha)
        ultima_marca = get_last_marca_by_empleado_fecha(empleado["id"], fecha)
        _validar_intervalo_minimo_marcas(ultima_marca, hora_salida, intervalo_minimo_fichadas)
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
        lowered = message.lower()
        code = getattr(exc, "status_code", 400) or 400
        if (
            "secuencia invalida" in lowered
            or "ya registrada" in lowered
            or "ya hay un ingreso abierto" in lowered
            or "duplicado" in lowered
        ):
            code = 409
        if "no hay fichada de entrada" in lowered:
            code = 404
        return jsonify(_api_error_body(message, exc)), code


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
            "imagen_version": _imagen_version_for_dni(refreshed.get("dni")),
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
    return jsonify({"ok": True, "foto": None, "imagen_version": None})


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


# ---------------------------------------------------------------------------
# Justificaciones del empleado autenticado
# ---------------------------------------------------------------------------

def _extract_justificacion_payload():
    source = request.form if request.form else (request.get_json(silent=True) or {})
    motivo = (source.get("motivo") or "").strip()
    archivo = (source.get("archivo") or "").strip() or None
    fecha_desde = (source.get("fecha_desde") or "").strip() or None
    fecha_hasta = (source.get("fecha_hasta") or "").strip() or None
    fecha = (source.get("fecha") or "").strip() or None
    raw_asistencia_id = source.get("asistencia_id")
    asistencia_id = _parse_int(raw_asistencia_id, "asistencia_id", default=None)
    return {
        "motivo": motivo,
        "archivo": archivo,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "fecha": fecha,
        "asistencia_id": asistencia_id,
        "asistencia_id_present": "asistencia_id" in source,
    }


def _extract_justificacion_files():
    archivos = request.files.getlist("adjuntos")
    if not archivos:
        archivos = request.files.getlist("adjuntos[]")
    if not archivos:
        archivo_unico = request.files.get("archivo_file")
        if not archivo_unico:
            archivo_unico = request.files.get("archivo")
        if archivo_unico and str(archivo_unico.filename or "").strip():
            archivos = [archivo_unico]
    return archivos


def _justificacion_adjunto_to_dict(row: dict, justificacion_id: int) -> dict:
    return justificacion_adjunto_to_mobile_dict(row, justificacion_id)


def _justificacion_to_dict(j: dict, adjuntos: list[dict] | None = None) -> dict:
    adjuntos_count = int(j.get("adjuntos_count") or 0)
    if adjuntos is not None:
        adjuntos_count = len(adjuntos)
    archivo = j.get("archivo") or None
    if not archivo and adjuntos:
        archivo = adjuntos[0].get("download_url")
    estado = j.get("estado") or "pendiente"
    resuelto_at = j.get("resuelto_at")
    visto_at = j.get("visto_por_empleado_at")
    return {
        "id": j["id"],
        "asistencia_id": j.get("asistencia_id"),
        "fecha": _to_date_str(j.get("fecha")) if j.get("fecha") else None,
        "fecha_desde": _to_date_str(j.get("fecha_desde")) if j.get("fecha_desde") else None,
        "fecha_hasta": _to_date_str(j.get("fecha_hasta")) if j.get("fecha_hasta") else None,
        "asistencia_fecha": _to_date_str(j.get("asistencia_fecha")) if j.get("asistencia_fecha") else None,
        "motivo": j.get("motivo"),
        "archivo": archivo,
        "estado": estado,
        "resuelto_at": resuelto_at.isoformat() if hasattr(resuelto_at, "isoformat") else (str(resuelto_at) if resuelto_at else None),
        "resuelto_by_usuario_id": j.get("resuelto_by_usuario_id"),
        "resuelto_by_usuario": j.get("resuelto_by_usuario"),
        "comentario_resolucion": j.get("comentario_resolucion"),
        "motivo_rechazo": j.get("motivo_rechazo"),
        "notificado_empleado_at": (
            j.get("notificado_empleado_at").isoformat()
            if hasattr(j.get("notificado_empleado_at"), "isoformat")
            else (str(j.get("notificado_empleado_at")) if j.get("notificado_empleado_at") else None)
        ),
        "visto_por_empleado_at": visto_at.isoformat() if hasattr(visto_at, "isoformat") else (str(visto_at) if visto_at else None),
        "tiene_novedad": estado in {"aprobada", "rechazada"} and bool(resuelto_at) and not bool(visto_at),
        "legajo_evento_id": j.get("legajo_evento_id"),
        "adjuntos_count": adjuntos_count,
        "adjuntos_max": MAX_JUSTIFICACION_ADJUNTOS,
        "adjuntos_disponibles": max(0, MAX_JUSTIFICACION_ADJUNTOS - adjuntos_count),
        "adjuntos": [
            _justificacion_adjunto_to_dict(a, int(j["id"]))
            for a in adjuntos or []
        ],
        "created_at": j["created_at"].isoformat() if hasattr(j.get("created_at"), "isoformat") else str(j.get("created_at") or ""),
    }


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>/marcar-vista", methods=["POST"])
@mobile_auth_required
def me_justificaciones_mark_seen(justificacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404
    if (j.get("estado") or "pendiente") == "pendiente":
        return jsonify({"error": "La justificacion aun no fue resuelta."}), 409

    marcar_justificacion_vista_por_empleado(justificacion_id, int(empleado["id"]))
    refreshed = get_justificacion_by_id(justificacion_id) or j
    return jsonify({"ok": True, "justificacion": _justificacion_to_dict(refreshed)})


@mobile_v1_bp.route("/me/justificaciones", methods=["GET"])
@mobile_auth_required
def me_justificaciones_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per", 20, type=int) or 20, 100))
    fecha_desde = (request.args.get("desde") or "").strip() or None
    fecha_hasta = (request.args.get("hasta") or "").strip() or None
    estado = (request.args.get("estado") or "").strip() or None

    if estado and estado not in {"pendiente", "aprobada", "rechazada"}:
        return jsonify({"error": "estado invalido. Valores: pendiente, aprobada, rechazada"}), 400

    rows, total = get_justificaciones_page(
        page=page,
        per_page=per_page,
        empleado_id=int(empleado["id"]),
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=estado,
    )

    return jsonify({
        "items": [_justificacion_to_dict(r) for r in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
    })


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>", methods=["GET"])
@mobile_auth_required
def me_justificaciones_detail(justificacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404

    adjuntos = list_justificacion_adjuntos(justificacion_id)
    return jsonify(_justificacion_to_dict(j, adjuntos))


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>/adjuntos", methods=["GET"])
@mobile_auth_required
def me_justificaciones_adjuntos_list(justificacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404

    adjuntos = list_justificacion_adjuntos(justificacion_id)
    return jsonify({
        "items": [_justificacion_adjunto_to_dict(a, justificacion_id) for a in adjuntos],
        "total": len(adjuntos),
    })


@mobile_v1_bp.route("/me/justificaciones", methods=["POST"])
@mobile_auth_required
def me_justificaciones_create():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = _extract_justificacion_payload()
    archivos = _extract_justificacion_files()
    adjuntos_guardados = []

    data = {
        "empleado_id": int(empleado["id"]),
        "asistencia_id": payload["asistencia_id"],
        "fecha_desde": payload["fecha_desde"],
        "fecha_hasta": payload["fecha_hasta"],
        "fecha": payload["fecha"],
        "motivo": payload["motivo"],
        "archivo": payload["archivo"],
        "estado": "pendiente",
    }
    try:
        just_id = create_justificacion_svc(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        # En mobile autenticamos como empleado, pero estos campos apuntan a usuarios.
        # No existe un usuario equivalente para todos los empleados, así que se dejan nulos.
        if archivos:
            adjuntos_guardados = save_justificacion_adjuntos(
                int(just_id),
                archivos,
                actor_id=None,
            )
        else:
            sync_justificacion_event(int(just_id), actor_id=None)
    except ValueError as e:
        try:
            delete_justificacion_resources(int(just_id), actor_id=None)
            delete_justificacion_row(just_id)
        except Exception:
            current_app.logger.exception("mobile_justificaciones_create_rollback_error")
        return jsonify({"error": str(e)}), 400
    except Exception:
        current_app.logger.exception("mobile_justificaciones_create_error", extra={"extra": {"justificacion_id": just_id}})
        try:
            delete_justificacion_resources(int(just_id), actor_id=None)
            delete_justificacion_row(just_id)
        except Exception:
            current_app.logger.exception("mobile_justificaciones_create_rollback_error")
        return jsonify({"error": "No se pudo guardar la justificacion."}), 500

    try:
        create_audit(None, "create", "justificaciones", just_id)
    except Exception:
        current_app.logger.warning("create_audit failed for justificaciones create", exc_info=True)
    j = get_justificacion_by_id(just_id)
    adjuntos = adjuntos_guardados or list_justificacion_adjuntos(just_id)
    return jsonify(_justificacion_to_dict(j, adjuntos)), 201


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>", methods=["PUT"])
@mobile_auth_required
def me_justificaciones_update(justificacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404

    if (j.get("estado") or "pendiente") != "pendiente":
        return jsonify({"error": f"Solo se puede editar una justificacion pendiente (estado actual: '{j.get('estado')}')"}), 409

    payload = _extract_justificacion_payload()
    archivos = _extract_justificacion_files()

    try:
        asistencia_id = payload["asistencia_id"] if payload["asistencia_id_present"] else j.get("asistencia_id")
        update_justificacion_svc(justificacion_id, {
            "empleado_id": j["empleado_id"],
            "asistencia_id": asistencia_id,
            "fecha": payload["fecha"] or j.get("fecha"),
            "fecha_desde": payload["fecha_desde"] or j.get("fecha_desde") or payload["fecha"] or j.get("fecha"),
            "fecha_hasta": payload["fecha_hasta"] or j.get("fecha_hasta") or payload["fecha"] or j.get("fecha"),
            "motivo": payload["motivo"],
            "archivo": payload["archivo"],
            "estado": j.get("estado") or "pendiente",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        if archivos:
            save_justificacion_adjuntos(
                int(justificacion_id),
                archivos,
                actor_id=None,
            )
        else:
            sync_justificacion_event(int(justificacion_id), actor_id=None)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        current_app.logger.exception("mobile_justificaciones_update_error", extra={"extra": {"justificacion_id": justificacion_id}})
        return jsonify({"error": "No se pudo actualizar la justificacion."}), 500

    try:
        create_audit(None, "update", "justificaciones", justificacion_id)
    except Exception:
        current_app.logger.warning("create_audit failed for justificaciones update", exc_info=True)
    j = get_justificacion_by_id(justificacion_id)
    adjuntos = list_justificacion_adjuntos(justificacion_id)
    return jsonify(_justificacion_to_dict(j, adjuntos))


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>", methods=["DELETE"])
@mobile_auth_required
def me_justificaciones_delete(justificacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404

    if (j.get("estado") or "pendiente") != "pendiente":
        return jsonify({"error": f"Solo se puede retirar una justificacion pendiente (estado actual: '{j.get('estado')}')"}), 409

    try:
        delete_justificacion_resources(int(justificacion_id), actor_id=None)
        delete_justificacion_row(justificacion_id)
    except Exception:
        current_app.logger.exception(
            "mobile_justificaciones_delete_error",
            extra={"extra": {"justificacion_id": justificacion_id}},
        )
        return jsonify({"error": "No se pudo eliminar la justificacion."}), 500
    try:
        create_audit(None, "delete", "justificaciones", justificacion_id)
    except Exception:
        current_app.logger.warning("create_audit failed for justificaciones delete", exc_info=True)
    return jsonify({"ok": True})


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>/adjuntos/<int:adjunto_id>", methods=["DELETE"])
@mobile_auth_required
def me_justificaciones_adjunto_delete(justificacion_id, adjunto_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404
    try:
        delete_justificacion_adjunto(justificacion_id, adjunto_id, actor_id=None)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "no encontrado" in message.lower() else 409
        return jsonify({"error": message}), status
    return jsonify({"ok": True})


@mobile_v1_bp.route("/me/justificaciones/<int:justificacion_id>/adjuntos/<int:adjunto_id>", methods=["GET"])
@mobile_auth_required
def me_justificaciones_adjunto(justificacion_id, adjunto_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    j = get_justificacion_by_id(justificacion_id)
    if not j or j.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Justificacion no encontrada"}), 404

    adjuntos = list_justificacion_adjuntos(justificacion_id)
    adjunto = next((a for a in adjuntos if int(a.get("id") or 0) == int(adjunto_id)), None)
    if not adjunto:
        return jsonify({"error": "Adjunto no encontrado"}), 404

    row = get_adjunto_by_id(adjunto_id)
    if not row or int(row.get("evento_justificacion_id") or 0) != int(justificacion_id):
        return jsonify({"error": "Adjunto no encontrado"}), 404
    if str(row.get("estado") or "").strip().lower() != "activo":
        return jsonify({"error": "Adjunto no encontrado"}), 404
    if str(row.get("evento_estado") or "").strip().lower() != "vigente":
        return jsonify({"error": "Adjunto no encontrado"}), 404

    download = str(request.args.get("download") or "").strip().lower() in {"1", "true", "yes"}
    backend = str(row.get("storage_backend") or "").strip().lower()
    if backend == "db":
        payload = get_adjunto_data_by_id(adjunto_id)
        if not payload:
            return jsonify({"error": "Adjunto no encontrado"}), 404
        response = Response(payload, mimetype=row.get("mime_type") or "application/octet-stream")
        response.headers["Cache-Control"] = "public, max-age=86400"
        if download:
            filename = str(row.get("nombre_original") or f"adjunto_{adjunto_id}.pdf").replace('"', "")
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    try:
        path = resolve_legajo_storage_path(row.get("storage_ruta"))
    except RuntimeError:
        return jsonify({"error": "Adjunto no encontrado"}), 404
    if not path.exists() or not path.is_file():
        return jsonify({"error": "Adjunto no encontrado"}), 404
    return send_file(
        str(path),
        mimetype=row.get("mime_type") or "application/octet-stream",
        as_attachment=download,
        download_name=row.get("nombre_original") or path.name,
        max_age=86400,
    )


# ---------------------------------------------------------------------------
# Vacaciones
# ---------------------------------------------------------------------------

def _vacacion_to_dict(v: dict) -> dict:
    fh = v.get("fecha_hasta")
    observaciones = v.get("observaciones")
    if observaciones is None:
        observaciones = v.get("observacion")
    return {
        "id": v.get("id"),
        "empleado_id": v.get("empleado_id"),
        "fecha_desde": _to_date_str(v.get("fecha_desde")),
        "fecha_hasta": _to_date_str(fh) if fh is not None else None,
        "observaciones": observaciones or "",
    }


@mobile_v1_bp.route("/me/vacaciones", methods=["GET"])
@mobile_auth_required
def me_vacaciones_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    fecha_desde = request.args.get("desde") or None
    fecha_hasta = request.args.get("hasta") or None

    rows, total = get_vacaciones_page_by_empleado(
        int(empleado["id"]), page, per_page,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
    )
    return jsonify({
        "items": [_vacacion_to_dict(v) for v in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@mobile_v1_bp.route("/me/vacaciones/<int:vacacion_id>", methods=["GET"])
@mobile_auth_required
def me_vacaciones_detail(vacacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    v = get_vacaciones_movimiento_by_id(vacacion_id)
    if not v or v.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Vacacion no encontrada"}), 404

    return jsonify(_vacacion_to_dict(v))


@mobile_v1_bp.route("/me/vacaciones", methods=["POST"])
@mobile_auth_required
def me_vacaciones_create():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    fecha_desde = (payload.get("fecha_desde") or "").strip() or None
    fecha_hasta = (payload.get("fecha_hasta") or "").strip() or None
    observaciones = (payload.get("observaciones") or "").strip() or None

    if not fecha_desde or not fecha_hasta:
        return jsonify({"error": "fecha_desde y fecha_hasta son requeridos"}), 400

    if fecha_desde > fecha_hasta:
        return jsonify({"error": "fecha_desde no puede ser posterior a fecha_hasta"}), 400

    try:
        solicitud = solicitar_vacaciones_svc(
            empleado_id=int(empleado["id"]),
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            observacion=observaciones,
        )
    except VacacionesSaldoInsuficienteError as exc:
        return jsonify({"error": str(exc)}), 409
    except VacacionesError as exc:
        return jsonify({"error": str(exc)}), 400

    v = get_vacaciones_movimiento_by_id(solicitud.get("id"))
    return jsonify(_vacacion_to_dict(v or solicitud)), 201


@mobile_v1_bp.route("/me/vacaciones/<int:vacacion_id>", methods=["PUT"])
@mobile_auth_required
def me_vacaciones_update(vacacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    v = get_vacaciones_movimiento_by_id(vacacion_id)
    if not v or v.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Vacacion no encontrada"}), 404
    if str(v.get("estado") or "").lower() != "pendiente":
        return jsonify({"error": "Solo se pueden editar vacaciones pendientes"}), 400

    payload = request.get_json(silent=True) or {}
    fecha_desde = (payload.get("fecha_desde") or "").strip() or None
    fecha_hasta = (payload.get("fecha_hasta") or "").strip() or None
    observaciones = (payload.get("observaciones") or "").strip() or None

    if not fecha_desde or not fecha_hasta:
        return jsonify({"error": "fecha_desde y fecha_hasta son requeridos"}), 400

    if fecha_desde > fecha_hasta:
        return jsonify({"error": "fecha_desde no puede ser posterior a fecha_hasta"}), 400

    try:
        anio = int(str(fecha_desde)[:4])
    except (TypeError, ValueError):
        return jsonify({"error": "fecha_desde invalida. Use YYYY-MM-DD."}), 400

    try:
        editar_movimiento_vacaciones_pendiente(
            vacacion_id,
            {
                "empleado_id": int(empleado["id"]),
                "anio": anio,
                "tipo": "tomado",
                "dias": "",
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "estado": "pendiente",
                "observacion": observaciones,
            },
        )
    except VacacionesSaldoInsuficienteError as exc:
        return jsonify({"error": str(exc)}), 409
    except VacacionesError as exc:
        return jsonify({"error": str(exc)}), 400
    v = get_vacaciones_movimiento_by_id(vacacion_id)
    return jsonify(_vacacion_to_dict(v))


@mobile_v1_bp.route("/me/vacaciones/<int:vacacion_id>", methods=["DELETE"])
@mobile_auth_required
def me_vacaciones_delete(vacacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    v = get_vacaciones_movimiento_by_id(vacacion_id)
    if not v or v.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Vacacion no encontrada"}), 404

    estado = str(v.get("estado") or "").lower()
    try:
        if estado == "pendiente":
            rechazar_movimiento_vacaciones(
                vacacion_id,
                actor_id=int(empleado["id"]),
                motivo="Cancelada por empleado",
            )
        elif estado == "aprobado":
            cancelar_movimiento_vacaciones(
                vacacion_id,
                actor_id=int(empleado["id"]),
                motivo="Cancelada por empleado",
            )
        else:
            return jsonify({"error": "La vacacion ya esta resuelta"}), 400
    except VacacionesError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Vacaciones movimientos / saldo LCT
# ---------------------------------------------------------------------------

def _parse_vacaciones_anio():
    raw = (request.args.get("anio") or "").strip()
    if not raw:
        return datetime.date.today().year, None
    try:
        anio = int(raw)
        if anio < 2000 or anio > 2100:
            raise ValueError
        return anio, None
    except ValueError:
        return None, jsonify({"ok": False, "error": "Anio invalido."}), 400


@mobile_v1_bp.route("/vacaciones/resumen", methods=["GET"])
@mobile_auth_required
def vacaciones_resumen():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    parsed = _parse_vacaciones_anio()
    if len(parsed) == 3:
        return parsed[1], parsed[2]
    anio, _ = parsed

    try:
        data = calcular_resumen_vacaciones(int(empleado["id"]), int(anio))
    except VacacionesError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "mobile_vacaciones_resumen_error",
            extra={"extra": {"empleado_id": empleado.get("id"), "anio": anio}},
        )
        return jsonify({"ok": False, "error": "No se pudo calcular el resumen de vacaciones."}), 500

    data["ok"] = True
    return jsonify(data)


@mobile_v1_bp.route("/vacaciones/movimientos", methods=["GET"])
@mobile_auth_required
def vacaciones_movimientos():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    parsed = _parse_vacaciones_anio()
    if len(parsed) == 3:
        return parsed[1], parsed[2]
    anio, _ = parsed

    try:
        data = listar_movimientos_vacaciones(int(empleado["id"]), int(anio))
    except VacacionesError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "mobile_vacaciones_movimientos_error",
            extra={"extra": {"empleado_id": empleado.get("id"), "anio": anio}},
        )
        return jsonify({"ok": False, "error": "No se pudieron obtener los movimientos de vacaciones."}), 500

    data["ok"] = True
    return jsonify(data)


@mobile_v1_bp.route("/vacaciones/solicitar", methods=["POST"])
@mobile_auth_required
def vacaciones_solicitar():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    try:
        solicitud = solicitar_vacaciones_svc(
            empleado_id=int(empleado["id"]),
            fecha_desde=payload.get("fecha_desde"),
            fecha_hasta=payload.get("fecha_hasta"),
            observacion=payload.get("observacion"),
        )
    except VacacionesSaldoInsuficienteError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except VacacionesError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "mobile_vacaciones_solicitar_error",
            extra={"extra": {"empleado_id": empleado.get("id")}},
        )
        return jsonify({"ok": False, "error": "No se pudo registrar la solicitud de vacaciones."}), 500

    try:
        create_audit(int(empleado["id"]), "create", "vacaciones_movimientos", solicitud.get("id"))
    except Exception:
        current_app.logger.warning(
            "create_audit failed for vacaciones_solicitar",
            exc_info=True,
            extra={"extra": {"empleado_id": empleado.get("id")}},
        )
    return jsonify(
        {
            "ok": True,
            "message": "Solicitud de vacaciones registrada correctamente",
            "solicitud": {
                "id": solicitud.get("id"),
                "dias_solicitados": solicitud.get("dias_solicitados"),
                "estado": solicitud.get("estado"),
                "fecha_desde": solicitud.get("fecha_desde"),
                "fecha_hasta": solicitud.get("fecha_hasta"),
            },
        }
    ), 201


# ---------------------------------------------------------------------------
# Adelantos
# ---------------------------------------------------------------------------

def _adelanto_to_dict(a: dict) -> dict:
    periodo_year = int(a.get("periodo_year") or 0)
    periodo_month = int(a.get("periodo_month") or 0)
    resolved_at = a.get("resuelto_at")
    return {
        "id": a.get("id"),
        "periodo": f"{periodo_year:04d}-{periodo_month:02d}",
        "periodo_year": periodo_year,
        "periodo_month": periodo_month,
        "fecha_solicitud": _to_date_str(a.get("fecha_solicitud")),
        "estado": a.get("estado") or "pendiente",
        "created_at": a["created_at"].isoformat() if hasattr(a.get("created_at"), "isoformat") else str(a.get("created_at") or ""),
        "resuelto_at": resolved_at.isoformat() if hasattr(resolved_at, "isoformat") else (str(resolved_at) if resolved_at else None),
        "resuelto_by_usuario": a.get("resuelto_by_usuario") or None,
    }


@mobile_v1_bp.route("/me/adelantos/resumen", methods=["GET"])
@mobile_auth_required
def me_adelantos_resumen():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    empleado_id = int(empleado["id"])
    today_iso = _today_iso()
    today = datetime.date.fromisoformat(today_iso)
    adelanto_mes_actual = get_adelanto_mes_actual_svc(
        empleado_id,
        fecha_solicitud=today_iso,
    )
    latest_rows, total_historial = get_adelantos_page_by_empleado(empleado_id, 1, 1)
    _, pendientes_total = get_adelantos_page_by_empleado(empleado_id, 1, 1, estado="pendiente")

    ultimo_adelanto = latest_rows[0] if latest_rows else None
    return jsonify(
        {
            "periodo": f"{today.year:04d}-{today.month:02d}",
            "periodo_year": today.year,
            "periodo_month": today.month,
            "ya_solicitado": adelanto_mes_actual is not None,
            "adelanto_mes_actual": _adelanto_to_dict(adelanto_mes_actual) if adelanto_mes_actual else None,
            "ultimo_adelanto": _adelanto_to_dict(ultimo_adelanto) if ultimo_adelanto else None,
            "total_historial": total_historial,
            "pendientes_total": pendientes_total,
        }
    )


@mobile_v1_bp.route("/me/adelantos", methods=["GET"])
@mobile_auth_required
def me_adelantos_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    estado = (request.args.get("estado") or "").strip() or None

    if estado and estado not in {"pendiente", "aprobado", "rechazado", "cancelado"}:
        return jsonify({"error": "estado invalido. Valores: pendiente, aprobado, rechazado, cancelado"}), 400

    rows, total = get_adelantos_page_by_empleado(
        int(empleado["id"]),
        page,
        per_page,
        estado=estado,
    )
    return jsonify(
        {
            "items": [_adelanto_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
    )


@mobile_v1_bp.route("/me/adelantos/<int:adelanto_id>", methods=["GET"])
@mobile_auth_required
def me_adelantos_detail(adelanto_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    adelanto = get_adelanto_by_id(adelanto_id)
    if not adelanto or int(adelanto.get("empleado_id") or 0) != int(empleado["id"]):
        return jsonify({"error": "Adelanto no encontrado"}), 404

    return jsonify(_adelanto_to_dict(adelanto))


@mobile_v1_bp.route("/me/adelantos/estado", methods=["GET"])
@mobile_auth_required
def me_adelantos_estado():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    today_iso = _today_iso()
    today = datetime.date.fromisoformat(today_iso)
    adelanto = get_adelanto_mes_actual_svc(
        int(empleado["id"]),
        fecha_solicitud=today_iso,
    )
    return jsonify(
        {
            "periodo": f"{today.year:04d}-{today.month:02d}",
            "periodo_year": today.year,
            "periodo_month": today.month,
            "ya_solicitado": adelanto is not None,
            "adelanto": _adelanto_to_dict(adelanto) if adelanto else None,
        }
    )


@mobile_v1_bp.route("/me/adelantos", methods=["POST"])
@mobile_auth_required
def me_adelantos_create():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    today_iso = _today_iso()
    try:
        adelanto_id = solicitar_adelanto_svc(
            empleado_id=int(empleado["id"]),
            empresa_id=empleado.get("empresa_id"),
            fecha_solicitud=today_iso,
        )
    except AdelantoAlreadyRequestedError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        create_audit(int(empleado["id"]), "create", "adelantos", adelanto_id)
    except Exception:
        current_app.logger.warning("create_audit failed for adelantos create", exc_info=True)
    adelanto = get_adelanto_by_id(adelanto_id)
    return jsonify(_adelanto_to_dict(adelanto)), 201


# ---------------------------------------------------------------------------
# Pedidos de mercaderia
# ---------------------------------------------------------------------------

def _pedido_mercaderia_item_to_dict(item: dict) -> dict:
    cantidad_bultos = int(item.get("cantidad_bultos") or 0)
    cantidad_unidades = int(item.get("cantidad_unidades") or 0)
    unidades_por_bulto = int(item.get("unidades_por_bulto_snapshot") or 0)
    return {
        "id": item.get("id"),
        "articulo_id": item.get("articulo_id"),
        "codigo_articulo": item.get("codigo_articulo_snapshot"),
        "descripcion": item.get("descripcion_snapshot"),
        "unidades_por_bulto": unidades_por_bulto,
        "cantidad_bultos": cantidad_bultos,
        "cantidad_unidades": cantidad_unidades,
        "total_unidades": cantidad_bultos * unidades_por_bulto + cantidad_unidades,
    }


def _pedido_mercaderia_to_dict(pedido: dict) -> dict:
    periodo_year = int(pedido.get("periodo_year") or 0)
    periodo_month = int(pedido.get("periodo_month") or 0)
    resolved_at = pedido.get("resuelto_at")
    return {
        "id": pedido.get("id"),
        "periodo": f"{periodo_year:04d}-{periodo_month:02d}",
        "periodo_year": periodo_year,
        "periodo_month": periodo_month,
        "fecha_pedido": _to_date_str(pedido.get("fecha_pedido")),
        "estado": pedido.get("estado") or "pendiente",
        "cantidad_items": int(pedido.get("cantidad_items") or 0),
        "total_bultos": int(pedido.get("total_bultos") or 0),
        "total_unidades": int(pedido.get("total_unidades") or 0),
        "motivo_rechazo": pedido.get("motivo_rechazo") or None,
        "created_at": pedido["created_at"].isoformat() if hasattr(pedido.get("created_at"), "isoformat") else str(pedido.get("created_at") or ""),
        "resuelto_at": resolved_at.isoformat() if hasattr(resolved_at, "isoformat") else (str(resolved_at) if resolved_at else None),
        "resuelto_by_usuario": pedido.get("resuelto_by_usuario") or None,
        "items": [_pedido_mercaderia_item_to_dict(item) for item in pedido.get("items") or []],
    }


def _articulo_catalogo_pedido_to_dict(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "codigo_articulo": row.get("codigo_articulo"),
        "descripcion": row.get("descripcion"),
        "unidades_por_bulto": int(row.get("unidades_por_bulto") or 0),
        "bultos_por_pallet": int(row.get("bultos_por_pallet") or 0) if row.get("bultos_por_pallet") is not None else None,
        "marca": row.get("marca") or None,
        "familia": row.get("familia") or None,
        "sabor": row.get("sabor") or None,
        "division": row.get("division") or None,
    }


@mobile_v1_bp.route("/me/pedidos-mercaderia/resumen", methods=["GET"])
@mobile_auth_required
def me_pedidos_mercaderia_resumen():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    empleado_id = int(empleado["id"])
    today_iso = _today_iso()
    today = datetime.date.fromisoformat(today_iso)
    pedido_mes_actual = get_pedido_mercaderia_mes_actual_svc(
        empleado_id,
        fecha_pedido=today_iso,
    )
    latest_rows, total_historial = get_pedidos_mercaderia_page_by_empleado(empleado_id, 1, 1)
    aprobados_rows, historial_aprobados_total = get_pedidos_mercaderia_page_by_empleado(
        empleado_id,
        1,
        1,
        estado="aprobado",
    )
    _, pendientes_total = get_pedidos_mercaderia_page_by_empleado(empleado_id, 1, 1, estado="pendiente")

    ultimo_pedido = latest_rows[0] if latest_rows else None
    ultimo_aprobado = aprobados_rows[0] if aprobados_rows else None
    return jsonify(
        {
            "periodo": f"{today.year:04d}-{today.month:02d}",
            "periodo_year": today.year,
            "periodo_month": today.month,
            "ya_solicitado": pedido_mes_actual is not None,
            "pedido_mes_actual": _pedido_mercaderia_to_dict(pedido_mes_actual) if pedido_mes_actual else None,
            "ultimo_pedido": _pedido_mercaderia_to_dict(ultimo_pedido) if ultimo_pedido else None,
            "ultimo_pedido_aprobado": _pedido_mercaderia_to_dict(ultimo_aprobado) if ultimo_aprobado else None,
            "total_historial": total_historial,
            "historial_aprobados_total": historial_aprobados_total,
            "pendientes_total": pendientes_total,
        }
    )


@mobile_v1_bp.route("/me/pedidos-mercaderia/estado", methods=["GET"])
@mobile_auth_required
def me_pedidos_mercaderia_estado():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    today_iso = _today_iso()
    today = datetime.date.fromisoformat(today_iso)
    pedido = get_pedido_mercaderia_mes_actual_svc(
        int(empleado["id"]),
        fecha_pedido=today_iso,
    )
    return jsonify(
        {
            "periodo": f"{today.year:04d}-{today.month:02d}",
            "periodo_year": today.year,
            "periodo_month": today.month,
            "ya_solicitado": pedido is not None,
            "pedido": _pedido_mercaderia_to_dict(pedido) if pedido else None,
        }
    )


@mobile_v1_bp.route("/me/pedidos-mercaderia/articulos", methods=["GET"])
@mobile_auth_required
def me_pedidos_mercaderia_articulos():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    search = (request.args.get("q") or "").strip() or None

    rows, total = get_articulos_catalogo_pedidos_page(
        page,
        per_page,
        search=search,
        habilitado_only=True,
    )
    return jsonify(
        {
            "items": [_articulo_catalogo_pedido_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
    )


@mobile_v1_bp.route("/me/pedidos-mercaderia", methods=["GET"])
@mobile_auth_required
def me_pedidos_mercaderia_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    estado = (request.args.get("estado") or "").strip() or None

    if estado and estado not in {"pendiente", "aprobado", "rechazado", "cancelado"}:
        return jsonify({"error": "estado invalido. Valores: pendiente, aprobado, rechazado, cancelado"}), 400

    rows, total = get_pedidos_mercaderia_page_by_empleado(
        int(empleado["id"]),
        page,
        per_page,
        estado=estado,
    )
    return jsonify(
        {
            "items": [_pedido_mercaderia_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
    )


@mobile_v1_bp.route("/me/pedidos-mercaderia/<int:pedido_id>", methods=["GET"])
@mobile_auth_required
def me_pedidos_mercaderia_detail(pedido_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    pedido = get_pedido_mercaderia_by_id(pedido_id)
    if not pedido or int(pedido.get("empleado_id") or 0) != int(empleado["id"]):
        return jsonify({"error": "Pedido no encontrado"}), 404

    return jsonify(_pedido_mercaderia_to_dict(pedido))


@mobile_v1_bp.route("/me/pedidos-mercaderia", methods=["POST"])
@mobile_auth_required
def me_pedidos_mercaderia_create():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    today_iso = _today_iso()
    try:
        pedido_id = solicitar_pedido_mercaderia_svc(
            empleado_id=int(empleado["id"]),
            empresa_id=empleado.get("empresa_id"),
            fecha_pedido=today_iso,
            items=payload.get("items"),
        )
    except PedidoMercaderiaAlreadyRequestedError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        create_audit(int(empleado["id"]), "create", "pedidos_mercaderia", pedido_id)
    except Exception:
        current_app.logger.warning("create_audit failed for pedidos_mercaderia create", exc_info=True)
    pedido = get_pedido_mercaderia_by_id(pedido_id)
    return jsonify(_pedido_mercaderia_to_dict(pedido)), 201


@mobile_v1_bp.route("/me/pedidos-mercaderia/<int:pedido_id>", methods=["PUT"])
@mobile_auth_required
def me_pedidos_mercaderia_update(pedido_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    try:
        editar_pedido_mercaderia_svc(
            pedido_id,
            empleado_id=int(empleado["id"]),
            items=payload.get("items"),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "no encontrado" in message.lower() else 400
        return jsonify({"error": message}), status

    try:
        create_audit(int(empleado["id"]), "update", "pedidos_mercaderia", pedido_id)
    except Exception:
        current_app.logger.warning("create_audit failed for pedidos_mercaderia update", exc_info=True)
    pedido = get_pedido_mercaderia_by_id(pedido_id)
    return jsonify(_pedido_mercaderia_to_dict(pedido))


@mobile_v1_bp.route("/me/pedidos-mercaderia/<int:pedido_id>", methods=["DELETE"])
@mobile_auth_required
def me_pedidos_mercaderia_cancel(pedido_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    try:
        cancelar_pedido_mercaderia_svc(
            pedido_id,
            empleado_id=int(empleado["id"]),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "no encontrado" in message.lower() else 400
        return jsonify({"error": message}), status

    try:
        create_audit(int(empleado["id"]), "cancel", "pedidos_mercaderia", pedido_id)
    except Exception:
        current_app.logger.warning("create_audit failed for pedidos_mercaderia cancel", exc_info=True)
    pedido = get_pedido_mercaderia_by_id(pedido_id)
    return jsonify(_pedido_mercaderia_to_dict(pedido))


# ---------------------------------------------------------------------------
# Horarios asignaciones
# ---------------------------------------------------------------------------

def _asignacion_to_dict(a: dict) -> dict:
    fh = a.get("fecha_hasta")
    return {
        "id": a.get("id"),
        "horario_id": a.get("horario_id"),
        "horario_nombre": a.get("horario_nombre") or "",
        "fecha_desde": _to_date_str(a.get("fecha_desde")),
        "fecha_hasta": _to_date_str(fh) if fh is not None else None,
    }


@mobile_v1_bp.route("/me/horarios-asignaciones", methods=["GET"])
@mobile_auth_required
def me_horarios_asignaciones_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    historial = get_horario_historial_by_empleado(int(empleado["id"]))
    return jsonify([_asignacion_to_dict(a) for a in historial])


@mobile_v1_bp.route("/me/horarios-asignaciones/actual", methods=["GET"])
@mobile_auth_required
def me_horarios_asignaciones_actual():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    actual = get_horario_actual_by_empleado(int(empleado["id"]))
    if not actual:
        return jsonify({"asignacion": None, "dias": []})

    dias = get_dias_by_horario(int(actual["horario_id"]))
    return jsonify({
        "asignacion": _asignacion_to_dict(actual),
        "dias": [{"dia_semana": d.get("dia_semana")} for d in dias],
    })


# ---------------------------------------------------------------------------
# Francos
# ---------------------------------------------------------------------------

def _franco_to_dict(f: dict) -> dict:
    return {
        "id": f.get("id"),
        "empleado_id": f.get("empleado_id"),
        "fecha": _to_date_str(f.get("fecha")),
        "motivo": f.get("motivo") or "",
    }


@mobile_v1_bp.route("/me/francos", methods=["GET"])
@mobile_auth_required
def me_francos_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    fecha_desde = request.args.get("desde") or None
    fecha_hasta = request.args.get("hasta") or None

    rows, total = get_francos_page_by_empleado(
        int(empleado["id"]), page, per_page,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
    )
    return jsonify({
        "items": [_franco_to_dict(f) for f in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@mobile_v1_bp.route("/me/francos/<int:franco_id>", methods=["GET"])
@mobile_auth_required
def me_francos_detail(franco_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    f = get_franco_by_id(franco_id)
    if not f or f.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Franco no encontrado"}), 404

    return jsonify(_franco_to_dict(f))


# ---------------------------------------------------------------------------
# Legajo eventos
# ---------------------------------------------------------------------------

def _evento_to_dict(e: dict, adjuntos: list[dict] | None = None) -> dict:
    return legajo_evento_to_mobile_dict(e, adjuntos=adjuntos)


def _parse_legajo_date_filter(value, label: str):
    try:
        return _parse_date(value)
    except ValueError as exc:
        raise ValueError(f"{label} invalida. Use YYYY-MM-DD.") from exc


def _parse_legajo_period(default_periodo: str = "anio_actual"):
    today_dt = datetime.date.today()
    periodo = (request.args.get("periodo") or default_periodo).strip().lower()
    if periodo == "7d":
        desde_dt = today_dt - datetime.timedelta(days=6)
        hasta_dt = today_dt
    elif periodo == "30d":
        desde_dt = today_dt - datetime.timedelta(days=29)
        hasta_dt = today_dt
    elif periodo == "90d":
        desde_dt = today_dt - datetime.timedelta(days=89)
        hasta_dt = today_dt
    elif periodo == "mes_actual":
        desde_dt = today_dt.replace(day=1)
        hasta_dt = today_dt
    elif periodo == "anio_actual":
        desde_dt = today_dt.replace(month=1, day=1)
        hasta_dt = today_dt
    elif periodo == "custom":
        desde_dt = today_dt.replace(month=1, day=1)
        hasta_dt = today_dt
    else:
        raise ValueError("periodo invalido.")

    raw_desde = (request.args.get("desde") or "").strip()
    raw_hasta = (request.args.get("hasta") or "").strip()
    if raw_desde or raw_hasta:
        if raw_desde:
            desde_dt = datetime.date.fromisoformat(_parse_legajo_date_filter(raw_desde, "desde"))
        if raw_hasta:
            hasta_dt = datetime.date.fromisoformat(_parse_legajo_date_filter(raw_hasta, "hasta"))
        periodo = "custom"

    if desde_dt > hasta_dt:
        raise ValueError("El rango de fechas es invalido (desde > hasta).")
    if (hasta_dt - desde_dt).days > 366:
        raise ValueError("El rango maximo permitido es 366 dias.")
    return periodo, desde_dt, hasta_dt


def _mobile_legajo_permiso_o_error(actor: dict):
    alcance = get_mobile_legajo_alcance(int(actor["id"]), PERMISO_CARGAR_EVENTOS_LEGAJO)
    if not alcance:
        return None, (jsonify({"ok": False, "error": "No tiene permisos para cargar eventos de legajo."}), 403)
    return alcance, None


def _mobile_legajo_empleado_visible(actor: dict, target: dict, alcance: str) -> bool:
    if not target or not target.get("activo"):
        return False
    if alcance == "global":
        return True
    if alcance == "propio":
        return int(target.get("id") or 0) == int(actor.get("id") or 0)
    if alcance == "empresa":
        return int(target.get("empresa_id") or 0) == int(actor.get("empresa_id") or 0)
    if alcance == "sucursal":
        return (
            int(target.get("empresa_id") or 0) == int(actor.get("empresa_id") or 0)
            and int(target.get("sucursal_id") or 0) == int(actor.get("sucursal_id") or 0)
        )
    if alcance == "equipo":
        return (
            int(target.get("empresa_id") or 0) == int(actor.get("empresa_id") or 0)
            and int(target.get("reporta_a_empleado_id") or 0) == int(actor.get("id") or 0)
        )
    return (
        int(target.get("empresa_id") or 0) == int(actor.get("empresa_id") or 0)
        and int(target.get("sector_id") or 0) == int(actor.get("sector_id") or 0)
    )


def _mobile_legajo_tipo_habilitado(tipo: dict | None) -> bool:
    return bool(tipo and tipo.get("activo") and tipo.get("habilitado_mobile"))


def _mobile_legajo_evento_payload():
    source = request.form if request.form else (request.get_json(silent=True) or {})
    try:
        tipo_id = _parse_int(source.get("tipo_id"), "tipo_id")
        empleado_id = _parse_int(source.get("empleado_id"), "empleado_id")
        fecha_evento = _parse_legajo_date_filter(source.get("fecha_evento"), "fecha_evento")
        fecha_desde = _parse_legajo_date_filter(source.get("fecha_desde"), "fecha_desde")
        fecha_hasta = _parse_legajo_date_filter(source.get("fecha_hasta"), "fecha_hasta")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    if not tipo_id:
        raise ValueError("tipo_id es obligatorio.")
    if not empleado_id:
        raise ValueError("empleado_id es obligatorio.")
    if not fecha_evento:
        raise ValueError("fecha_evento es obligatoria.")
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise ValueError("El rango de fechas es invalido (fecha_desde > fecha_hasta).")

    severidad = str(source.get("severidad") or "").strip().lower() or None
    if severidad and severidad not in {"leve", "media", "grave"}:
        raise ValueError("severidad debe ser 'leve', 'media' o 'grave'.")

    descripcion = str(source.get("descripcion") or "").strip()
    if not descripcion:
        raise ValueError("descripcion es obligatoria.")

    return {
        "empleado_id": empleado_id,
        "tipo_id": tipo_id,
        "fecha_evento": fecha_evento,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "titulo": str(source.get("titulo") or "").strip() or None,
        "descripcion": descripcion,
        "severidad": severidad,
    }


def _mobile_legajo_files():
    files = []
    for key in ("adjuntos", "adjunto", "archivo", "evidencia"):
        files.extend(request.files.getlist(key))
    return [file for file in files if file and str(file.filename or "").strip()]


def _save_mobile_legajo_adjuntos(files, *, evento_id: int, empresa_id: int, empleado_id: int):
    saved_items = []
    for file_storage in files:
        saved = save_legajo_attachment_local(
            file_storage,
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            evento_id=evento_id,
        )
        adjunto_id = create_adjunto(
            {
                "evento_id": evento_id,
                "empresa_id": empresa_id,
                "empleado_id": empleado_id,
                "nombre_original": saved["nombre_original"],
                "mime_type": saved["mime_type"],
                "extension": saved["extension"],
                "tamano_bytes": saved["tamano_bytes"],
                "sha256": saved["sha256"],
                "storage_backend": saved["storage_backend"],
                "storage_ruta": saved["storage_ruta"],
                "storage_data": saved.get("storage_data"),
                "created_by_usuario_id": None,
            }
        )
        saved_items.append({"id": adjunto_id, **saved})
    return saved_items


@mobile_v1_bp.route("/me/legajo/eventos-admin/permisos", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_admin_permisos():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    alcance, error_response = _mobile_legajo_permiso_o_error(empleado)
    if error_response:
        return jsonify({
            "ok": True,
            "puede_cargar": False,
            "permiso": PERMISO_CARGAR_EVENTOS_LEGAJO,
            "alcance": None,
        })
    return jsonify({
        "ok": True,
        "puede_cargar": True,
        "permiso": PERMISO_CARGAR_EVENTOS_LEGAJO,
        "alcance": alcance,
    })


@mobile_v1_bp.route("/me/legajo/eventos-admin/empleados", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_admin_empleados():
    actor = _mobile_user()
    if not actor:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401
    alcance, error_response = _mobile_legajo_permiso_o_error(actor)
    if error_response:
        return error_response

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    search = (request.args.get("q") or request.args.get("search") or "").strip() or None

    empresa_id = int(actor["empresa_id"]) if alcance in {"empresa", "sucursal", "sector", "equipo", "propio"} and actor.get("empresa_id") else None
    sucursal_id = int(actor["sucursal_id"]) if alcance == "sucursal" and actor.get("sucursal_id") else None
    sector_id = int(actor["sector_id"]) if alcance == "sector" and actor.get("sector_id") else None

    rows, total = get_empleados_page(
        page,
        per_page,
        include_inactive=False,
        search=search,
        empresa_id=empresa_id,
        activo=1,
        sucursal_id=sucursal_id,
        sector_id=sector_id,
    )
    if alcance in {"equipo", "propio"}:
        filtered = [row for row in rows if _mobile_legajo_empleado_visible(actor, row, alcance)]
        rows = filtered
        total = len(filtered)

    return jsonify({
        "ok": True,
        "items": [
            {
                "id": row.get("id"),
                "empresa_id": row.get("empresa_id"),
                "legajo": row.get("legajo"),
                "dni": row.get("dni"),
                "apellido": row.get("apellido"),
                "nombre": row.get("nombre"),
                "display_name": f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip(),
                "empresa_nombre": row.get("empresa_nombre"),
                "sucursal_id": row.get("sucursal_id"),
                "sucursal_nombre": row.get("sucursal_nombre"),
                "sector_id": row.get("sector_id"),
                "sector_nombre": row.get("sector_nombre"),
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "alcance": alcance,
    })


@mobile_v1_bp.route("/me/legajo/eventos-admin/tipos", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_admin_tipos():
    actor = _mobile_user()
    if not actor:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401
    _, error_response = _mobile_legajo_permiso_o_error(actor)
    if error_response:
        return error_response

    tipos = get_tipos_evento(include_inactive=False, habilitado_mobile=1)
    return jsonify({
        "ok": True,
        "items": [legajo_tipo_evento_to_mobile_dict(tipo) for tipo in tipos],
        "total": len(tipos),
    })


@mobile_v1_bp.route("/me/legajo/eventos-admin", methods=["POST"])
@mobile_auth_required
def me_legajo_eventos_admin_create():
    actor = _mobile_user()
    if not actor:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401
    alcance, error_response = _mobile_legajo_permiso_o_error(actor)
    if error_response:
        return error_response

    try:
        payload = _mobile_legajo_evento_payload()
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    target = get_empleado_by_id(int(payload["empleado_id"]))
    if not _mobile_legajo_empleado_visible(actor, target, alcance):
        return jsonify({"ok": False, "error": "No tiene permisos para cargar eventos sobre este empleado."}), 403

    tipo = get_tipo_evento_by_id(int(payload["tipo_id"]))
    if not _mobile_legajo_tipo_habilitado(tipo):
        return jsonify({"ok": False, "error": "Tipo de evento no habilitado para carga mobile."}), 400
    if tipo.get("requiere_rango_fechas") and (not payload.get("fecha_desde") or not payload.get("fecha_hasta")):
        return jsonify({"ok": False, "error": "Este tipo de evento requiere fecha_desde y fecha_hasta."}), 400

    files = _mobile_legajo_files()
    if files and not tipo.get("permite_adjuntos"):
        return jsonify({"ok": False, "error": "Este tipo de evento no permite adjuntos."}), 400

    evento_id = create_evento(
        {
            "empresa_id": int(target["empresa_id"]),
            "empleado_id": int(target["id"]),
            "tipo_id": int(payload["tipo_id"]),
            "fecha_evento": payload["fecha_evento"],
            "fecha_desde": payload["fecha_desde"],
            "fecha_hasta": payload["fecha_hasta"],
            "titulo": payload["titulo"],
            "descripcion": payload["descripcion"],
            "estado": "vigente",
            "severidad": payload["severidad"],
            "created_by_usuario_id": None,
            "updated_by_usuario_id": None,
        }
    )

    try:
        adjuntos = _save_mobile_legajo_adjuntos(
            files,
            evento_id=int(evento_id),
            empresa_id=int(target["empresa_id"]),
            empleado_id=int(target["id"]),
        ) if files else []
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception("mobile_legajo_eventos_admin_adjuntos_error", extra={"extra": {"evento_id": evento_id}})
        return jsonify({"ok": False, "error": "El evento fue creado, pero no se pudieron guardar los adjuntos."}), 500

    evento = get_evento_by_id_for_empleado(int(evento_id), int(target["id"]), int(target["empresa_id"]))
    return jsonify({
        "ok": True,
        "evento": _evento_to_dict(evento or {"id": evento_id, **payload, "empresa_id": target["empresa_id"]}),
        "adjuntos_guardados": len(adjuntos),
    }), 201


@mobile_v1_bp.route("/me/legajo/resumen", methods=["GET"])
@mobile_auth_required
def me_legajo_resumen():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    try:
        periodo, desde_dt, hasta_dt = _parse_legajo_period()
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        resumen = calcular_resumen_legajo(int(empleado["id"]), desde_dt, hasta_dt)
    except Exception:
        current_app.logger.exception(
            "mobile_legajo_resumen_error",
            extra={"extra": {"empleado_id": empleado.get("id")}},
        )
        return jsonify({"ok": False, "error": "No se pudo calcular el resumen de legajo."}), 500

    return jsonify({
        "ok": True,
        "periodo": {
            "desde": desde_dt.isoformat(),
            "hasta": hasta_dt.isoformat(),
            "preset": periodo,
        },
        "resumen": resumen,
    })


@mobile_v1_bp.route("/me/legajo/tipos-evento", methods=["GET"])
@mobile_auth_required
def me_legajo_tipos_evento():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    try:
        tipos = get_tipos_evento(include_inactive=False)
    except Exception:
        current_app.logger.exception(
            "mobile_legajo_tipos_error",
            extra={"extra": {"empleado_id": empleado.get("id")}},
        )
        return jsonify({"ok": False, "error": "No se pudieron obtener los tipos de evento."}), 500

    return jsonify({
        "ok": True,
        "items": [legajo_tipo_evento_to_mobile_dict(tipo) for tipo in tipos],
        "total": len(tipos),
    })


@mobile_v1_bp.route("/me/legajo/eventos", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))

    try:
        tipo_id = _parse_int(request.args.get("tipo_id"), "tipo_id", default=None)
        fecha_desde = _parse_legajo_date_filter(request.args.get("desde"), "desde")
        fecha_hasta = _parse_legajo_date_filter(request.args.get("hasta"), "hasta")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        return jsonify({"ok": False, "error": "El rango de fechas es invalido (desde > hasta)."}), 400

    estado_raw = (request.args.get("estado") or "").strip().lower()
    estado = None if estado_raw in {"", "all", "todos"} else estado_raw
    if estado and estado not in {"vigente", "anulado"}:
        return jsonify({"ok": False, "error": "estado debe ser 'vigente' o 'anulado'"}), 400

    severidad_raw = (request.args.get("severidad") or "").strip().lower()
    severidad = None if severidad_raw in {"", "all", "todos"} else severidad_raw
    if severidad and severidad not in {"leve", "media", "grave"}:
        return jsonify({"ok": False, "error": "severidad debe ser 'leve', 'media' o 'grave'"}), 400

    search = (request.args.get("q") or request.args.get("search") or "").strip() or None

    rows, total = get_eventos_page(
        page, per_page,
        search=search,
        empleado_id=int(empleado["id"]),
        empresa_id=int(empleado["empresa_id"]) if empleado.get("empresa_id") else None,
        tipo_id=tipo_id,
        estado=estado,
        severidad=severidad,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    return jsonify({
        "ok": True,
        "items": [_evento_to_dict(e) for e in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "has_more": page * per_page < total,
        },
    })


@mobile_v1_bp.route("/me/legajo/eventos/<int:evento_id>", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_detail(evento_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    e = get_evento_by_id_for_empleado(
        int(evento_id),
        int(empleado["id"]),
        int(empleado["empresa_id"]) if empleado.get("empresa_id") else None,
    )
    if not e:
        return jsonify({"ok": False, "error": "Evento no encontrado"}), 404

    body = _evento_to_dict(e)
    body["ok"] = True
    return jsonify(body)


@mobile_v1_bp.route("/me/legajo/adjuntos/<int:adjunto_id>", methods=["GET"])
@mobile_auth_required
def me_legajo_adjunto(adjunto_id):
    return jsonify({"ok": False, "error": "No autorizado"}), 403


@mobile_v1_bp.route("/me/legajo/historial-por-tipo", methods=["GET"])
@mobile_auth_required
def me_legajo_historial_por_tipo():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"ok": False, "error": "Empleado no encontrado o inactivo"}), 401

    try:
        filas = get_conteo_por_tipo_for_empleado(int(empleado["id"]))
    except Exception:
        current_app.logger.exception(
            "mobile_legajo_historial_por_tipo_error",
            extra={"extra": {"empleado_id": empleado.get("id")}},
        )
        return jsonify({"ok": False, "error": "No se pudo obtener el historial por tipo."}), 500

    items = [
        {
            "tipo_id": int(f["tipo_id"]),
            "codigo": f["codigo"] or "",
            "nombre": f["nombre"] or "",
            "total": int(f["total"] or 0),
            "vigentes": int(f["vigentes"] or 0),
            "ultima_fecha": f["ultima_fecha"].isoformat() if f.get("ultima_fecha") else None,
        }
        for f in filas
    ]
    return jsonify({"ok": True, "items": items, "total_tipos": len(items)})


# ---------------------------------------------------------------------------
# Dashboard consolidado — home screen de la app
# ---------------------------------------------------------------------------

def _legajo_stats_for_mobile(empleado_id: int, desde_dt: datetime.date, hasta_dt: datetime.date):
    """Aggregate legajo events for the dashboard endpoint."""
    return calcular_resumen_legajo(int(empleado_id), desde_dt, hasta_dt)


@mobile_v1_bp.route("/me/dashboard", methods=["GET"])
@mobile_auth_required
def me_dashboard():
    """
    Consolidated dashboard endpoint for the mobile home screen.

    Query params:
      - desde  (date, ISO) — default: 30 days ago
      - hasta  (date, ISO) — default: today
      - periodo (str)      — "7d" | "30d" | "mes_actual" | "custom" (overrides desde/hasta)
    """
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    today_dt = datetime.date.today()
    today_iso = today_dt.isoformat()

    periodo = (request.args.get("periodo") or "30d").strip().lower()
    if periodo == "7d":
        desde_dt = today_dt - datetime.timedelta(days=6)
        hasta_dt = today_dt
    elif periodo == "mes_actual":
        desde_dt = today_dt.replace(day=1)
        hasta_dt = today_dt
    elif periodo == "90d":
        desde_dt = today_dt - datetime.timedelta(days=89)
        hasta_dt = today_dt
    else:
        periodo = "30d"
        desde_dt = today_dt - datetime.timedelta(days=29)
        hasta_dt = today_dt

    # Allow custom override
    raw_desde = (request.args.get("desde") or "").strip()
    raw_hasta = (request.args.get("hasta") or "").strip()
    if raw_desde or raw_hasta:
        try:
            if raw_desde:
                desde_dt = datetime.date.fromisoformat(raw_desde)
            if raw_hasta:
                hasta_dt = datetime.date.fromisoformat(raw_hasta)
            periodo = "custom"
        except ValueError:
            return jsonify({"error": "Rango de fechas invalido"}), 400

    if desde_dt > today_dt:
        desde_dt = today_dt
    if hasta_dt > today_dt:
        hasta_dt = today_dt
    if desde_dt > hasta_dt:
        return jsonify({"error": "El rango de fechas es invalido (desde > hasta)."}), 400
    if (hasta_dt - desde_dt).days > 366:
        return jsonify({"error": "El rango maximo permitido es 366 dias."}), 400

    fecha_desde = desde_dt.isoformat()
    fecha_hasta = hasta_dt.isoformat()
    emp_id = int(empleado["id"])

    try:
        stats = get_mobile_stats_by_empleado(
            empleado_id=emp_id,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except Exception:
        current_app.logger.exception("me_dashboard_stats_error", extra={"extra": {"empleado_id": emp_id}})
        return jsonify({"error": "No se pudo calcular el dashboard."}), 500

    try:
        legajo = _legajo_stats_for_mobile(emp_id, desde_dt, hasta_dt)
    except Exception:
        current_app.logger.exception("me_dashboard_legajo_error", extra={"extra": {"empleado_id": emp_id}})
        legajo = {}

    # Vacaciones activas o futuras (desde hoy)
    try:
        vac_rows, _ = get_vacaciones_page_by_empleado(emp_id, 1, 10, fecha_desde=today_iso)
        vacaciones_activas = [_vacacion_to_dict(v) for v in vac_rows]
    except Exception:
        vacaciones_activas = []

    # Francos próximos 30 días
    try:
        proximos_hasta = (today_dt + datetime.timedelta(days=30)).isoformat()
        franco_rows, _ = get_francos_page_by_empleado(emp_id, 1, 10, fecha_desde=today_iso, fecha_hasta=proximos_hasta)
        francos_proximos = [_franco_to_dict(f) for f in franco_rows]
    except Exception:
        francos_proximos = []

    # Horario actual
    try:
        horario = get_horario_actual_by_empleado(emp_id)
        dias = get_dias_by_horario(int(horario["id"])) if horario else []
        horario_actual = _asignacion_to_dict(horario) if horario else None
        if horario_actual and dias:
            horario_actual["dias"] = [_dia_to_dict(d) for d in dias]
    except Exception:
        horario_actual = None

    return jsonify({
        "periodo": {
            "desde": fecha_desde,
            "hasta": fecha_hasta,
            "preset": periodo,
            "dias_habiles": (stats or {}).get("kpis", {}).get("dias_laborables", 0),
        },
        "asistencia": stats or {},
        "legajo": legajo,
        "vacaciones_activas": vacaciones_activas,
        "francos_proximos": francos_proximos,
        "horario_actual": horario_actual,
    })


# ---------------------------------------------------------------------------
# KPIs Sectoriales
# ---------------------------------------------------------------------------

@mobile_v1_bp.route("/me/kpis-sector", methods=["GET"])
@mobile_auth_required
def me_kpis_sector():
    from repositories.kpi_sectorial_repository import get_resultados_empleado_anio

    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    emp_id = int(empleado["id"])

    raw_anio = (request.args.get("anio") or "").strip()
    if raw_anio:
        try:
            anio = int(raw_anio)
            if anio < 2020 or anio > 2100:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Ano invalido."}), 400
    else:
        anio = datetime.date.today().year

    try:
        data = get_resultados_empleado_anio(emp_id, anio)
    except Exception:
        current_app.logger.exception("me_kpis_sector_error", extra={"extra": {"empleado_id": emp_id}})
        return jsonify({"error": "No se pudieron obtener los KPIs."}), 500

    return jsonify({
        "anio": anio,
        "sector": {
            "id": data.get("sector_id"),
            "nombre": data.get("sector_nombre"),
        },
        "kpis": data.get("kpis", []),
    })


@mobile_v1_bp.route("/me/kpis-sector/dia", methods=["GET"])
@mobile_auth_required
def me_kpis_sector_dia():
    from repositories.kpi_sectorial_repository import get_kpis_dia_empleado

    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    emp_id = int(empleado["id"])

    raw_fecha = (request.args.get("fecha") or "").strip()
    if not raw_fecha:
        return jsonify({"error": "El parametro fecha es obligatorio (YYYY-MM-DD)."}), 400
    try:
        fecha = datetime.date.fromisoformat(raw_fecha)
        if fecha > datetime.date.today():
            return jsonify({"error": "La fecha no puede ser futura."}), 400
    except ValueError:
        return jsonify({"error": "Fecha invalida. Use formato YYYY-MM-DD."}), 400

    try:
        data = get_kpis_dia_empleado(emp_id, fecha)
    except Exception:
        current_app.logger.exception("me_kpis_sector_dia_error", extra={"extra": {"empleado_id": emp_id}})
        return jsonify({"error": "No se pudieron obtener los KPIs del dia."}), 500

    return jsonify({
        "fecha": fecha.isoformat(),
        "sector": {
            "id": data.get("sector_id"),
            "nombre": data.get("sector_nombre"),
        },
        "kpis": data.get("kpis", []),
    })


@mobile_v1_bp.route("/me/kpis-sector/resumen", methods=["GET"])
@mobile_auth_required
def me_kpis_sector_resumen():
    from repositories.kpi_sectorial_repository import (
        get_resultados_empleado_anio,
        get_resultados_empleado_meses_cerrados,
        get_ultimo_resultado_cargado_empleado,
        get_series_diaria_empleado,
    )

    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    emp_id = int(empleado["id"])

    raw_anio = (request.args.get("anio") or "").strip()
    if raw_anio:
        try:
            anio = int(raw_anio)
            if anio < 2020 or anio > 2100:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Ano invalido."}), 400
    else:
        anio = datetime.date.today().year

    raw_limit = (request.args.get("limit_meses") or "6").strip()
    try:
        limit_meses = int(raw_limit)
        if limit_meses < 1 or limit_meses > 12:
            raise ValueError
    except ValueError:
        return jsonify({"error": "limit_meses invalido. Use un entero entre 1 y 12."}), 400

    include_series = (request.args.get("include_series") or "").strip().lower() in ("1", "true")
    raw_series_dias = (request.args.get("series_dias") or "60").strip()
    try:
        series_dias = int(raw_series_dias)
        if series_dias < 1 or series_dias > 365:
            raise ValueError
    except ValueError:
        return jsonify({"error": "series_dias invalido. Use un entero entre 1 y 365."}), 400

    try:
        data = get_resultados_empleado_anio(emp_id, anio)
        ultimo = get_ultimo_resultado_cargado_empleado(emp_id, anio)
        meses_cerrados = get_resultados_empleado_meses_cerrados(emp_id, anio, limit_meses)
        series_diaria = get_series_diaria_empleado(emp_id, anio, series_dias) if include_series else None
    except Exception:
        current_app.logger.exception("me_kpis_sector_resumen_error", extra={"extra": {"empleado_id": emp_id}})
        return jsonify({"error": "No se pudieron obtener las vistas de KPIs."}), 500

    payload = {
        "anio": anio,
        "sector": {
            "id": data.get("sector_id"),
            "nombre": data.get("sector_nombre"),
        },
        "vista_actual": {
            "kpis": data.get("kpis", []),
        },
        "ultimo_cargado": ultimo,
        "meses_cerrados": meses_cerrados,
        "meta": {
            "limit_meses": limit_meses,
            "include_series": include_series,
            "series_dias": series_dias if include_series else None,
        },
    }
    if include_series:
        payload["series_diaria"] = series_diaria
    return jsonify(payload)


# ---------------------------------------------------------------------------
# Premios y concursos
# ---------------------------------------------------------------------------

def _premio_resultado_to_dict(row: dict) -> dict:
    periodo_year = int(row.get("periodo_year") or 0)
    periodo_month = int(row.get("periodo_month") or 0)
    periodo = row.get("periodo_label") or (f"{periodo_year:04d}-{periodo_month:02d}" if periodo_year and periodo_month else None)
    concurso_sector_id = row.get("concurso_sector_id")
    return {
        "id": row.get("id"),
        "periodo": periodo,
        "periodo_year": periodo_year,
        "periodo_month": periodo_month,
        "mes_nombre": PREMIO_MONTH_NAMES.get(periodo_month),
        "ranking": int(row.get("ranking") or 0),
        "observaciones": row.get("observaciones"),
        "concurso": {
            "id": row.get("concurso_id"),
            "codigo": row.get("concurso_codigo"),
            "nombre": row.get("concurso_nombre"),
            "descripcion": row.get("concurso_descripcion"),
            "alcance": row.get("concurso_alcance"),
            "sector": {
                "id": concurso_sector_id,
                "nombre": row.get("concurso_sector_nombre"),
            } if concurso_sector_id else None,
        },
        "sector_empleado": {
            "id": row.get("empleado_sector_id"),
            "nombre": row.get("empleado_sector_nombre"),
        } if row.get("empleado_sector_id") else None,
    }


@mobile_v1_bp.route("/me/premios", methods=["GET"])
@mobile_auth_required
def me_premios():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401
    emp_id = int(empleado["id"])

    raw_anio = (request.args.get("anio") or "").strip()
    if raw_anio:
        try:
            anio = int(raw_anio)
            if anio < 2020 or anio > 2100:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Ano invalido."}), 400
    else:
        anio = datetime.date.today().year

    try:
        data = get_premios_resultados_empleado_anio(emp_id, anio)
    except Exception:
        current_app.logger.exception("me_premios_error", extra={"extra": {"empleado_id": emp_id}})
        return jsonify({"error": "No se pudieron obtener los premios."}), 500

    meses = [
        {
            "mes": month,
            "nombre": PREMIO_MONTH_NAMES[month],
            "premios": [],
        }
        for month in range(1, 13)
    ]
    rankings = []
    for row in data.get("premios", []):
        item = _premio_resultado_to_dict(row)
        month = int(item.get("periodo_month") or 0)
        if 1 <= month <= 12:
            meses[month - 1]["premios"].append(item)
        if item.get("ranking"):
            rankings.append(int(item["ranking"]))

    return jsonify({
        "anio": anio,
        "sector": {
            "id": data.get("sector_id"),
            "nombre": data.get("sector_nombre"),
        },
        "resumen": {
            "total_premios": len(rankings),
            "mejor_ranking": min(rankings) if rankings else None,
            "primeros_puestos": sum(1 for ranking in rankings if ranking == 1),
            "podios": sum(1 for ranking in rankings if ranking <= 3),
        },
        "meses": meses,
    })


@mobile_v1_bp.route("/calificar-app", methods=["POST"])
@mobile_auth_required
def calificar_app():
    from repositories.calificacion_app_repository import (
        create_calificacion,
        existe_calificacion,
    )

    empleado = _mobile_user()
    body = request.get_json(silent=True) or {}

    puntuacion = body.get("puntuacion")
    if puntuacion is None or not isinstance(puntuacion, int) or not (1 <= puntuacion <= 5):
        return jsonify({"ok": False, "error": "puntuacion debe ser un entero entre 1 y 5"}), 400

    version_app = str(body.get("version_app") or "").strip() or None

    if existe_calificacion(empleado["id"], version_app):
        return jsonify({"ok": False, "error": "Ya calificaste esta versión de la app"}), 409

    nuevo_id = create_calificacion({
        "empleado_id": empleado["id"],
        "dni": str(empleado.get("dni") or ""),
        "puntuacion": puntuacion,
        "comentario": str(body.get("comentario") or "").strip() or None,
        "pantalla": str(body.get("pantalla") or "").strip() or None,
        "version_app": version_app,
    })

    return jsonify({"ok": True, "id": nuevo_id}), 201
