import datetime
import re

from flask import Blueprint, current_app, g, jsonify, request
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
    update_mobile_profile,
    update_password as update_empleado_password,
)
from repositories.legajo_evento_repository import (
    get_eventos_page,
    get_evento_by_id,
    get_eventos_by_empleado as get_todos_eventos_by_empleado,
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
    get_by_id as get_vacacion_by_id,
    create as create_vacacion_row,
    update as update_vacacion_row,
    delete as delete_vacacion_row,
)
from repositories.justificacion_repository import (
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
from repositories.pedido_mercaderia_repository import (
    get_by_id as get_pedido_mercaderia_by_id,
    get_page_by_empleado as get_pedidos_mercaderia_page_by_empleado,
)
from repositories.mobile_stats_repository import get_by_empleado as get_mobile_stats_by_empleado
from repositories.auditoria_repository import create as create_audit
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
from utils.jwt import generar_token, generar_token_qr, verificar_token_qr
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
        raise ValueError("qr_token requerido para metodo qr.")
    payload = verificar_token_qr(token, accion_esperada=accion)
    token_empresa = int(payload.get("empresa_id"))
    if token_empresa != int(empleado["empresa_id"]):
        raise ValueError("QR no corresponde a la empresa del empleado.")
    token_empleado = payload.get("empleado_id")
    if token_empleado is not None and int(token_empleado) != int(empleado["id"]):
        raise ValueError("QR no corresponde al empleado autenticado.")
    return payload


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


@mobile_v1_bp.route("/auth/login", methods=["POST"])
def auth_login():
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
                "imagen_version": _imagen_version_for_dni(user.get("dni")),
            },
        }
    )


@mobile_v1_bp.route("/auth/refresh", methods=["POST"])
@mobile_auth_required
def auth_refresh():
    empleado = _mobile_user()
    if not empleado:
        current_app.logger.info("mobile_auth_refresh_failed", extra={"extra": {"reason": "inactive_or_missing"}})
        return jsonify({"error": INVALID_SESSION_MESSAGE}), 401

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

def _justificacion_to_dict(j: dict) -> dict:
    return {
        "id": j["id"],
        "asistencia_id": j.get("asistencia_id"),
        "asistencia_fecha": _to_date_str(j.get("asistencia_fecha")) if j.get("asistencia_fecha") else None,
        "motivo": j.get("motivo"),
        "archivo": j.get("archivo") or None,
        "estado": j.get("estado") or "pendiente",
        "created_at": j["created_at"].isoformat() if hasattr(j.get("created_at"), "isoformat") else str(j.get("created_at") or ""),
    }


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

    return jsonify(_justificacion_to_dict(j))


@mobile_v1_bp.route("/me/justificaciones", methods=["POST"])
@mobile_auth_required
def me_justificaciones_create():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    payload = request.get_json(silent=True) or {}
    motivo = (payload.get("motivo") or "").strip()
    archivo = (payload.get("archivo") or "").strip() or None
    raw_asistencia_id = payload.get("asistencia_id")
    asistencia_id = int(raw_asistencia_id) if raw_asistencia_id is not None else None

    data = {
        "empleado_id": int(empleado["id"]),
        "asistencia_id": asistencia_id,
        "motivo": motivo,
        "archivo": archivo,
        "estado": "pendiente",
    }
    try:
        just_id = create_justificacion_svc(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    create_audit(int(empleado["id"]), "create", "justificaciones", just_id)
    j = get_justificacion_by_id(just_id)
    return jsonify(_justificacion_to_dict(j)), 201


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

    payload = request.get_json(silent=True) or {}
    motivo = (payload.get("motivo") or "").strip()
    archivo = (payload.get("archivo") or "").strip() or None

    try:
        update_justificacion_svc(justificacion_id, {
            "empleado_id": j["empleado_id"],
            "asistencia_id": j.get("asistencia_id"),
            "motivo": motivo,
            "archivo": archivo,
            "estado": j.get("estado") or "pendiente",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    create_audit(int(empleado["id"]), "update", "justificaciones", justificacion_id)
    j = get_justificacion_by_id(justificacion_id)
    return jsonify(_justificacion_to_dict(j))


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

    delete_justificacion_row(justificacion_id)
    create_audit(int(empleado["id"]), "delete", "justificaciones", justificacion_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Vacaciones
# ---------------------------------------------------------------------------

def _vacacion_to_dict(v: dict) -> dict:
    fh = v.get("fecha_hasta")
    return {
        "id": v.get("id"),
        "empleado_id": v.get("empleado_id"),
        "fecha_desde": _to_date_str(v.get("fecha_desde")),
        "fecha_hasta": _to_date_str(fh) if fh is not None else None,
        "observaciones": v.get("observaciones") or "",
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

    v = get_vacacion_by_id(vacacion_id)
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

    data = {
        "empleado_id": int(empleado["id"]),
        "empresa_id": empleado.get("empresa_id"),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "observaciones": observaciones,
    }
    vac_id = create_vacacion_row(data)
    v = get_vacacion_by_id(vac_id)
    return jsonify(_vacacion_to_dict(v)), 201


@mobile_v1_bp.route("/me/vacaciones/<int:vacacion_id>", methods=["PUT"])
@mobile_auth_required
def me_vacaciones_update(vacacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    v = get_vacacion_by_id(vacacion_id)
    if not v or v.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Vacacion no encontrada"}), 404

    payload = request.get_json(silent=True) or {}
    fecha_desde = (payload.get("fecha_desde") or "").strip() or None
    fecha_hasta = (payload.get("fecha_hasta") or "").strip() or None
    observaciones = (payload.get("observaciones") or "").strip() or None

    if not fecha_desde or not fecha_hasta:
        return jsonify({"error": "fecha_desde y fecha_hasta son requeridos"}), 400

    if fecha_desde > fecha_hasta:
        return jsonify({"error": "fecha_desde no puede ser posterior a fecha_hasta"}), 400

    update_vacacion_row(vacacion_id, {
        "empleado_id": int(empleado["id"]),
        "empresa_id": v.get("empresa_id"),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "observaciones": observaciones,
    })
    v = get_vacacion_by_id(vacacion_id)
    return jsonify(_vacacion_to_dict(v))


@mobile_v1_bp.route("/me/vacaciones/<int:vacacion_id>", methods=["DELETE"])
@mobile_auth_required
def me_vacaciones_delete(vacacion_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    v = get_vacacion_by_id(vacacion_id)
    if not v or v.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Vacacion no encontrada"}), 404

    delete_vacacion_row(vacacion_id)
    return jsonify({"ok": True})


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

    create_audit(int(empleado["id"]), "create", "adelantos", adelanto_id)
    adelanto = get_adelanto_by_id(adelanto_id)
    return jsonify(_adelanto_to_dict(adelanto)), 201


# ---------------------------------------------------------------------------
# Pedidos de mercaderia
# ---------------------------------------------------------------------------

def _pedido_mercaderia_item_to_dict(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "articulo_id": item.get("articulo_id"),
        "codigo_articulo": item.get("codigo_articulo_snapshot"),
        "descripcion": item.get("descripcion_snapshot"),
        "unidades_por_bulto": int(item.get("unidades_por_bulto_snapshot") or 0),
        "cantidad_bultos": int(item.get("cantidad_bultos") or 0),
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

    create_audit(int(empleado["id"]), "create", "pedidos_mercaderia", pedido_id)
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

    create_audit(int(empleado["id"]), "update", "pedidos_mercaderia", pedido_id)
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

    create_audit(int(empleado["id"]), "cancel", "pedidos_mercaderia", pedido_id)
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

def _evento_to_dict(e: dict) -> dict:
    fh = e.get("fecha_hasta")
    fd = e.get("fecha_desde")
    return {
        "id": e.get("id"),
        "tipo_id": e.get("tipo_id"),
        "tipo_codigo": e.get("tipo_codigo") or "",
        "tipo_nombre": e.get("tipo_nombre") or "",
        "fecha_evento": _to_date_str(e.get("fecha_evento")),
        "fecha_desde": _to_date_str(fd) if fd is not None else None,
        "fecha_hasta": _to_date_str(fh) if fh is not None else None,
        "titulo": e.get("titulo") or "",
        "descripcion": e.get("descripcion") or "",
        "estado": e.get("estado") or "vigente",
        "severidad": e.get("severidad"),
    }


@mobile_v1_bp.route("/me/legajo/eventos", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_list():
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = max(1, min(request.args.get("per_page", 20, type=int) or 20, 100))
    tipo_id_raw = request.args.get("tipo_id")
    tipo_id = int(tipo_id_raw) if tipo_id_raw else None
    estado = request.args.get("estado") or None
    if estado and estado not in {"vigente", "anulado"}:
        return jsonify({"error": "estado debe ser 'vigente' o 'anulado'"}), 400

    rows, total = get_eventos_page(
        page, per_page,
        empleado_id=int(empleado["id"]),
        tipo_id=tipo_id,
        estado=estado,
    )
    return jsonify({
        "items": [_evento_to_dict(e) for e in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@mobile_v1_bp.route("/me/legajo/eventos/<int:evento_id>", methods=["GET"])
@mobile_auth_required
def me_legajo_eventos_detail(evento_id):
    empleado = _mobile_user()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 401

    e = get_evento_by_id(evento_id)
    if not e or e.get("empleado_id") != int(empleado["id"]):
        return jsonify({"error": "Evento no encontrado"}), 404

    return jsonify(_evento_to_dict(e))


# ---------------------------------------------------------------------------
# Dashboard consolidado — home screen de la app
# ---------------------------------------------------------------------------

def _legajo_stats_for_mobile(empleado_id: int, desde_dt: datetime.date, hasta_dt: datetime.date):
    """Aggregate legajo events for the dashboard endpoint."""
    from collections import defaultdict
    all_events = get_todos_eventos_by_empleado(empleado_id, include_anulados=True)

    hist_vigentes = sum(1 for e in all_events if str(e.get("estado") or "").lower() == "vigente")
    hist_anulados = len(all_events) - hist_vigentes

    def _fe_date(ev):
        fe = ev.get("fecha_evento")
        if fe is None:
            return None
        if hasattr(fe, "date"):
            return fe.date()
        if isinstance(fe, datetime.date):
            return fe
        try:
            return datetime.date.fromisoformat(str(fe)[:10])
        except ValueError:
            return None

    periodo_vigentes = [
        e for e in all_events
        if str(e.get("estado") or "").lower() == "vigente"
        and (lambda d: d is not None and desde_dt <= d <= hasta_dt)(_fe_date(e))
    ]

    tipo_counts = defaultdict(lambda: {"label": "", "total": 0})
    sev_counts = defaultdict(int)
    for e in periodo_vigentes:
        tid = e.get("tipo_id")
        tipo_counts[tid]["label"] = e.get("tipo_nombre") or e.get("tipo_codigo") or str(tid)
        tipo_counts[tid]["total"] += 1
        sev_counts[str(e.get("severidad") or "").lower() or "sin_severidad"] += 1

    tipo_total = sum(d["total"] for d in tipo_counts.values()) or 1
    por_tipo = sorted(
        [{"label": d["label"], "total": d["total"], "pct": round(d["total"] * 100 / tipo_total, 1)}
         for d in tipo_counts.values()],
        key=lambda x: -x["total"],
    )

    sev_total = sum(sev_counts.values()) or 1
    por_severidad = [
        {"severidad": sev, "total": cnt, "pct": round(cnt * 100 / sev_total, 1)}
        for sev, cnt in sorted(sev_counts.items(), key=lambda x: -x[1])
    ]

    recientes = sorted(periodo_vigentes, key=lambda e: str(e.get("fecha_evento") or ""), reverse=True)[:5]

    return {
        "historico": {
            "total": len(all_events),
            "vigentes": hist_vigentes,
            "anulados": hist_anulados,
        },
        "periodo": {
            "total": len(periodo_vigentes),
            "graves": sum(1 for e in periodo_vigentes if str(e.get("severidad") or "").lower() == "grave"),
            "media": sum(1 for e in periodo_vigentes if str(e.get("severidad") or "").lower() == "media"),
            "leve": sum(1 for e in periodo_vigentes if str(e.get("severidad") or "").lower() == "leve"),
        },
        "por_tipo": por_tipo,
        "por_severidad": por_severidad,
        "recientes": [_evento_to_dict(e) for e in recientes],
    }


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
