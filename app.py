from datetime import timedelta

from flask import Flask, g, has_request_context, redirect, url_for, request, jsonify, render_template, session
from flask_cors import CORS
from dotenv import load_dotenv
import hashlib
import os
import logging
import json
import re
import secrets
import time
import uuid
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from utils.limiter import limiter

from extensions import get_db, init_db
from db import DatabaseConfigError
from routes.auth_routes import auth_bp          # API
from routes.external_api_routes import external_api_bp
from routes.mobile_v1_routes import mobile_v1_bp
from routes.media_routes import media_bp, public_media_bp
from web.auth.web_auth_routes import web_auth_bp  # WEB
from web.web_routes import web_bp
from web.presencia_routes import presencia_bp
from web.empleados.empleados_routes import empleados_bp
from web.empresas.empresas_routes import empresas_bp
from web.sucursales.sucursales_routes import sucursales_bp
from web.horarios.horarios_routes import horarios_bp
from web.roles.roles_routes import roles_bp
from web.roles.empleado_roles_routes import empleado_roles_bp
from web.empleado_horarios.empleado_horarios_routes import empleado_horarios_bp
from web.asistencias.asistencias_routes import asistencias_bp
from web.asistencias.egresos_automaticos_routes import egresos_automaticos_bp
from web.justificaciones.justificaciones_routes import justificaciones_bp
from web.auditoria.auditoria_routes import auditoria_bp
from web.usuarios.usuarios_routes import usuarios_bp
from web.configuracion.configuracion_empresa_routes import configuracion_bp
from web.sectores.sectores_routes import sectores_bp
from web.puestos.puestos_routes import puestos_bp
from web.organigrama.organigrama_routes import organigrama_bp
from web.localidades.localidades_routes import localidades_bp
from web.francos.francos_routes import francos_bp
from web.vacaciones.vacaciones_routes import vacaciones_bp
from web.adelantos.adelantos_routes import adelantos_bp
from web.pedidos_mercaderia.pedidos_mercaderia_routes import pedidos_mercaderia_bp
from web.empleado_excepciones.empleado_excepciones_routes import empleado_excepciones_bp
from web.qr_puerta.qr_puerta_routes import qr_puerta_bp
from web.legajos.legajos_routes import legajos_bp
from web.legajos.legajo_tipos_evento_routes import legajo_tipos_evento_bp
from web.kpis_sectoriales.kpis_sectoriales_routes import kpis_sectoriales_bp
from web.compromiso.compromiso_routes import compromiso_bp
from web.premios_concursos.premios_concursos_routes import premios_concursos_bp
from web.app_version.app_version_routes import app_version_bp
from web.feedback.feedback_routes import feedback_web_bp
from web.skap.skap_routes import skap_web_bp
from web.skap.matriz_routes import skap_matriz_bp
from routes.trivia_routes import trivia_bp
from web.trivias.trivia_admin_routes import trivia_admin_bp
from web.calificaciones_app.calificaciones_app_routes import calificaciones_app_bp
from web.mobile_stats.mobile_stats_routes import mobile_stats_bp
from routes.feedback_routes import feedback_bp
from routes.skap_routes import skap_bp
from routes.carga_routes import carga_mobile_bp
from routes.reintegro_routes import reintegros_mobile_bp
from web.epp.routes import web as epp_web_bp, mobile as epp_mobile_bp
from web.reintegros.reintegro_routes import reintegros_web_bp
from routes.seguridad_routes import seguridad_mobile_bp
from web.seguridad.seguridad_routes import seguridad_web_bp
from web.carga.carga_routes import carga_web_bp
from web.panel_notifications_routes import panel_notifications_bp
from web.rendimiento.rendimiento_routes import rendimiento_bp
from web.reuniones.routes import web as reuniones_web_bp, mobile as reuniones_mobile_bp
from web.push.routes import web as push_web_bp, mobile as push_mobile_bp
from web.comunicados.routes import web as comunicados_web_bp, mobile as comunicados_mobile_bp
from web.jornada.routes import web as jornada_web_bp
from web.horas.routes import web as horas_web_bp
from web.horas_extras.routes import web as horas_extras_web_bp
from web.banco_horas.routes import web as banco_horas_web_bp
from web.mapa_fichadas.routes import web as mapa_fichadas_web_bp
from routes.notificaciones_routes import mobile as notificaciones_mobile_bp
from routes.vacaciones_semanas_routes import mobile as vacaciones_semanas_mobile_bp
from utils import request_metrics

# API: autentican por token, responden errores en JSON y quedan exentas de CSRF.
API_BLUEPRINTS = (
    auth_bp,
    external_api_bp,
    mobile_v1_bp,
    feedback_bp,
    skap_bp,
    carga_mobile_bp,
    reintegros_mobile_bp,
    epp_mobile_bp,
    seguridad_mobile_bp,
    reuniones_mobile_bp,
    push_mobile_bp,
    comunicados_mobile_bp,
    notificaciones_mobile_bp,
    vacaciones_semanas_mobile_bp,
    trivia_bp,
)
API_BLUEPRINT_NAMES = frozenset(bp.name for bp in API_BLUEPRINTS)

# Orden de registro: Flask resuelve reglas duplicadas por orden de alta.
BLUEPRINTS = (
    auth_bp,
    external_api_bp,
    mobile_v1_bp,
    feedback_bp,
    skap_bp,
    carga_mobile_bp,
    reintegros_mobile_bp,
    epp_mobile_bp,
    epp_web_bp,
    reuniones_mobile_bp,
    reuniones_web_bp,
    push_mobile_bp,
    push_web_bp,
    comunicados_mobile_bp,
    comunicados_web_bp,
    jornada_web_bp,
    horas_web_bp,
    horas_extras_web_bp,
    banco_horas_web_bp,
    mapa_fichadas_web_bp,
    notificaciones_mobile_bp,
    vacaciones_semanas_mobile_bp,
    reintegros_web_bp,
    seguridad_mobile_bp,
    seguridad_web_bp,
    carga_web_bp,
    media_bp,
    public_media_bp,
    # Panel web
    web_auth_bp,
    web_bp,
    presencia_bp,
    empleados_bp,
    empresas_bp,
    sucursales_bp,
    horarios_bp,
    roles_bp,
    empleado_roles_bp,
    empleado_horarios_bp,
    asistencias_bp,
    egresos_automaticos_bp,
    justificaciones_bp,
    auditoria_bp,
    usuarios_bp,
    configuracion_bp,
    sectores_bp,
    puestos_bp,
    organigrama_bp,
    localidades_bp,
    francos_bp,
    vacaciones_bp,
    adelantos_bp,
    pedidos_mercaderia_bp,
    empleado_excepciones_bp,
    qr_puerta_bp,
    legajos_bp,
    legajo_tipos_evento_bp,
    kpis_sectoriales_bp,
    compromiso_bp,
    premios_concursos_bp,
    app_version_bp,
    trivia_admin_bp,
    calificaciones_app_bp,
    mobile_stats_bp,
    feedback_web_bp,
    skap_web_bp,
    skap_matriz_bp,
    panel_notifications_bp,
    rendimiento_bp,
    trivia_bp,
)

# Módulos con carga de archivos: límite de cuerpo y de partes multipart.
UPLOAD_MAX_BYTES = 27 * 1024 * 1024
UPLOAD_MAX_FORM_PARTS = {
    "reintegros_web": 700,
    "reintegros_mobile": 200,
    "seguridad_web": 150,
    "seguridad_mobile": 150,
    "epp_web": 150,
    "epp_mobile": 150,
}

load_dotenv("/etc/secrets/.env", override=False)
load_dotenv(override=False)

_PLACEHOLDER_SECRET_VALUES = {
    "changeme",
    "default",
    "default_secret",
    "dev_secret",
    "secret",
    "your-secret-key",
}
_VALID_SAMESITE_VALUES = {
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
}


class AppConfigError(RuntimeError):
    pass


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _request_id() -> str:
    """Id del request para correlacionar logs, respuesta y reporte del usuario.
    Reusa el X-Request-ID del proxy si es seguro; si no, genera uno."""
    request_id = getattr(g, "request_id", None)
    if not request_id:
        incoming = str(request.headers.get("X-Request-ID") or "").strip()
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex[:16]
        g.request_id = request_id
    return request_id


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AppConfigError(
        f"{name} invalida. Use 1/0, true/false, yes/no u on/off."
    )


def _parse_int_env(
    name: str,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise AppConfigError(f"{name} invalida. Debe ser un entero.") from exc
    if minimum is not None and value < minimum:
        raise AppConfigError(f"{name} debe ser mayor o igual a {minimum}.")
    if maximum is not None and value > maximum:
        raise AppConfigError(f"{name} debe ser menor o igual a {maximum}.")
    return value


def _app_env() -> str:
    return str(os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "production").strip().lower()


def _require_secret_key() -> str:
    secret = str(os.getenv("SECRET_KEY") or "").strip()
    if not secret:
        raise AppConfigError("SECRET_KEY no configurada.")
    if secret.lower() in _PLACEHOLDER_SECRET_VALUES:
        raise AppConfigError(
            "SECRET_KEY tiene un valor inseguro de plantilla. Configure una clave real."
        )
    if len(secret) < 32:
        raise AppConfigError("SECRET_KEY debe tener al menos 32 caracteres.")
    return secret


def _require_jwt_secret() -> None:
    """Impide iniciar la app sin la clave estable que firma tokens y QR."""
    secret = str(os.getenv("JWT_SECRET") or "").strip()
    if not secret:
        raise AppConfigError("JWT_SECRET no configurada.")
    if secret.lower() in _PLACEHOLDER_SECRET_VALUES:
        raise AppConfigError(
            "JWT_SECRET tiene un valor inseguro de plantilla. Configure una clave real y persistente."
        )
    if len(secret) < 32:
        raise AppConfigError("JWT_SECRET debe tener al menos 32 caracteres.")


def _jwt_secret_fingerprint() -> str:
    return hashlib.sha256(os.getenv("JWT_SECRET", "").encode("utf-8")).hexdigest()[:16]


def _check_jwt_secret_integrity(app) -> None:
    """Detecta si JWT_SECRET cambio respecto del ultimo deploy que arranco
    con exito. No bloquea el arranque (el valor actual ya es el que sirve
    trafico), pero deja un log critico inconfundible: un cambio silencioso
    de esta clave invalida los QR de puerta y los tokens moviles vigentes
    sin previo aviso. Ver docs/railway_deploy.md."""
    fingerprint = _jwt_secret_fingerprint()
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT config_value FROM system_config WHERE config_key = 'jwt_secret_fingerprint'"
            )
            row = cursor.fetchone()
            previous = row["config_value"] if row else None
            if previous and previous != fingerprint:
                app.logger.error(
                    "jwt_secret_changed",
                    extra={
                        "extra": {
                            "previous_fingerprint": previous,
                            "current_fingerprint": fingerprint,
                            "impact": (
                                "QR de puerta y tokens moviles emitidos antes de "
                                "este deploy dejaron de validar."
                            ),
                        }
                    },
                )
            cursor.execute(
                """
                INSERT INTO system_config (config_key, config_value)
                VALUES ('jwt_secret_fingerprint', %s)
                ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
                """,
                (fingerprint,),
            )
            db.commit()
        finally:
            cursor.close()
            db.close()
    except Exception:
        app.logger.exception("jwt_secret_integrity_check_failed")


_CSP_BASE = "base-uri 'self'; object-src 'none'; frame-ancestors 'self'"
_CSP_REPORT_MAX_BYTES = 16 * 1024


def _csp_nonce() -> str:
    """Nonce por request para los <script> inline de las plantillas."""
    nonce = getattr(g, "csp_nonce", None)
    if not nonce:
        nonce = g.csp_nonce = secrets.token_urlsafe(16)
    return nonce


def _strict_csp(nonce: str) -> str:
    return "; ".join((
        _CSP_BASE,
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "script-src-attr 'none'",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
        # Las fotos pueden servirse desde un host externo (FTP/CDN).
        "img-src 'self' data: blob: https:",
        "connect-src 'self'",
        "form-action 'self'",
        "report-uri /csp-report",
    ))


def _session_cookie_samesite() -> str:
    raw = str(os.getenv("SESSION_COOKIE_SAMESITE") or "Lax").strip().lower()
    value = _VALID_SAMESITE_VALUES.get(raw)
    if not value:
        raise AppConfigError(
            "SESSION_COOKIE_SAMESITE invalida. Use Lax, Strict o None."
        )
    return value


def _session_cookie_secure_default() -> bool:
    return _app_env() not in {"dev", "development", "local", "test"}


def _build_security_config() -> dict:
    _require_jwt_secret()
    session_cookie_secure = _parse_bool_env(
        "SESSION_COOKIE_SECURE",
        default=_session_cookie_secure_default(),
    )
    session_cookie_samesite = _session_cookie_samesite()
    if session_cookie_samesite == "None" and not session_cookie_secure:
        raise AppConfigError(
            "SESSION_COOKIE_SECURE debe ser true cuando SESSION_COOKIE_SAMESITE=None."
        )

    session_cookie_name = str(
        os.getenv("SESSION_COOKIE_NAME") or "control_asistencia_session"
    ).strip()
    if not session_cookie_name:
        raise AppConfigError("SESSION_COOKIE_NAME no puede ser vacia.")

    session_lifetime_minutes = _parse_int_env(
        "SESSION_LIFETIME_MINUTES",
        default=240,
        minimum=5,
        maximum=43200,
    )

    return {
        "MAX_CONTENT_LENGTH": _parse_int_env('MAX_REQUEST_BYTES', default=128*1024*1024, minimum=1024),
        "SECRET_KEY": _require_secret_key(),
        "SESSION_COOKIE_NAME": session_cookie_name,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": session_cookie_samesite,
        "SESSION_COOKIE_SECURE": session_cookie_secure,
        "PERMANENT_SESSION_LIFETIME": timedelta(minutes=session_lifetime_minutes),
        "SESSION_REFRESH_EACH_REQUEST": False,
        # La CSP estricta se publica en modo Report-Only hasta activar esto.
        "CSP_ENFORCE": _parse_bool_env("CSP_ENFORCE", default=False),
    }


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    app.config.update(_build_security_config())
    from utils.static_assets import init_static_assets
    init_static_assets(app)
    app.config["RATELIMIT_STORAGE_URI"] = os.getenv("RATELIMIT_STORAGE_URI") or "memory://"

    # Rate limiting: desactivar en entorno test para no afectar tests unitarios.
    if _app_env() in {"test", "testing"}:
        app.config.setdefault("RATELIMIT_ENABLED", False)
    limiter.init_app(app)

    # CORS: restringir a las rutas API y a los orígenes configurados.
    # Configurar CORS_ALLOWED_ORIGINS en .env como lista separada por comas.
    # Ejemplo: CORS_ALLOWED_ORIGINS=https://miapp.com,https://app2.com
    _cors_raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if _cors_raw == "*":
        _cors_origins = "*"
    elif _cors_raw:
        _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    else:
        _cors_origins = "*"  # por compatibilidad: móvil nativo no usa CORS
    CORS(
        app,
        resources={r"/auth/*": {}, r"/api/*": {}},
        origins=_cors_origins,
        supports_credentials=False,
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    init_db()

    # Logging (structured)
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            payload = {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "time": self.formatTime(record, self.datefmt)
            }
            if has_request_context():
                payload["request_id"] = _request_id()
            if hasattr(record, "extra"):
                payload.update(record.extra)
            if record.exc_info:
                import traceback
                payload["traceback"] = "".join(traceback.format_exception(*record.exc_info))
            return json.dumps(payload, ensure_ascii=False)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = []
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    app.logger.info(
        "app_boot",
        extra={
            "extra": {
                "app_env": _app_env(),
                "jwt_secret_fingerprint": _jwt_secret_fingerprint(),
            }
        },
    )
    _check_jwt_secret_integrity(app)

    # Security
    @app.before_request
    def seguridad_upload_limits():
        # Antes de CSRF: el formulario multipart no debe analizarse sin límite.
        max_form_parts = UPLOAD_MAX_FORM_PARTS.get(request.blueprint)
        if max_form_parts is not None:
            request.max_content_length = UPLOAD_MAX_BYTES
            request.max_form_parts = max_form_parts

    csrf = CSRFProtect(app)
    for blueprint in API_BLUEPRINTS:
        csrf.exempt(blueprint)
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    from services.panel_export_service import build_export_toolbar, wrap_exportable_views
    wrap_exportable_views(app)

    # Metricas del modulo Rendimiento: se vuelcan a la base cada minuto.
    if _app_env() not in {"test", "testing"}:
        request_metrics.start_flusher()

    # Scheduler de trivia (solo en entornos no-test y cuando se usa gunicorn/run)
    if _app_env() not in {"test", "testing"} and _parse_bool_env("SCHEDULER_IN_WEB", default=False):
        from utils.trivia_scheduler import init_trivia_scheduler
        init_trivia_scheduler(app)
        from utils.reintegro_scheduler import init_reintegro_scheduler
        init_reintegro_scheduler(app)

    @app.route("/")
    def index():
        return redirect(url_for("web_auth.login"))

    @app.route("/healthz")
    def healthz():
        return jsonify({
            "status": "ok",
            "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("BUILD_REVISION") or "local",
        }), 200

    @app.route("/csp-report", methods=["POST"])
    @csrf.exempt
    @limiter.limit("60 per minute")
    def csp_report():
        if (request.content_length or 0) > _CSP_REPORT_MAX_BYTES:
            return "", 413
        payload = request.get_json(force=True, silent=True) or {}
        reports = payload if isinstance(payload, list) else [payload]
        for item in reports[:10]:
            if not isinstance(item, dict):
                continue
            report = item.get("csp-report") or item.get("body") or {}
            if not isinstance(report, dict):
                continue
            app.logger.warning(
                "csp_violation",
                extra={
                    "extra": {
                        key.replace("-", "_"): str(report.get(key) or "")[:300]
                        for key in (
                            "document-uri", "violated-directive", "effective-directive",
                            "blocked-uri", "source-file", "line-number",
                        )
                    }
                },
            )
        return "", 204

    @app.errorhandler(CSRFError)
    def handle_csrf_error(err):
        message = "Sesion expirada o formulario invalido. Recargue la pagina e intente nuevamente."
        if request.path == "/login":
            return render_template("login.html", error=message), 400
        return _format_error(err, status_code=400)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return _format_error(err)

    @app.errorhandler(Exception)
    def handle_exception(err):
        if app.debug:
            # En desarrollo dejamos que Flask muestre traceback/debugger.
            raise err

        app.logger.exception(
            "Unhandled exception",
            extra={
                "extra": {
                    "path": request.path,
                    "method": request.method
                }
            }
        )
        return _format_error(err, status_code=500)

    def _format_error(err, status_code=None):
        code = status_code or getattr(err, "code", 500)
        message = getattr(err, "description", "Error interno")
        if code == 403:
            message = "Usuario no permitido."

        # En errores 500 el id permite ubicar el traceback en los logs.
        request_id = _request_id() if code >= 500 else None
        if request.blueprint in API_BLUEPRINT_NAMES:
            body = {"success": False, "error": message}
            if request_id:
                body["request_id"] = request_id
            return jsonify(body), code

        return render_template("error.html", code=code, message=message, request_id=request_id), code

    @app.before_request
    def _start_timer():
        request._start_time = time.time()
        _request_id()

    @app.after_request
    def _htmx_login_redirect(response):
        # Sin esto htmx seguiria la redireccion y pondria el login dentro del panel.
        if request.headers.get("HX-Request") and response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location") or ""
            if location.split("?")[0].rstrip("/").endswith("/login"):
                response.status_code = 204
                response.headers["HX-Redirect"] = location
                del response.headers["Location"]
                response.set_data(b"")
        return response

    @app.after_request
    def _add_security_headers(response):
        response.headers["X-Request-ID"] = _request_id()
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if response.mimetype == "text/html":
            strict = _strict_csp(_csp_nonce())
            if app.config["CSP_ENFORCE"]:
                response.headers.setdefault("Content-Security-Policy", strict)
            else:
                response.headers.setdefault("Content-Security-Policy-Report-Only", strict)
        response.headers.setdefault("Content-Security-Policy", _CSP_BASE)
        # Never let shared caches retain authenticated pages or API responses.
        # Static resources keep their conditional caching behaviour.
        if request.endpoint != 'static' and (
            session.get('user_id') or request.headers.get('Authorization')
            or request.headers.get('X-API-Key') or request.path in ('/login', '/auth/login')
        ):
            response.headers['Cache-Control'] = 'private, no-store'
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.after_request
    def _log_request(response):
        if request.path.startswith("/static/") and response.status_code < 400:
            return response

        elapsed = None
        if hasattr(request, "_start_time"):
            elapsed = round((time.time() - request._start_time) * 1000, 2)
        if elapsed is not None:
            response.headers["Server-Timing"] = f"app;dur={elapsed}"
            if hasattr(g, 'db_ms'):
                response.headers["Server-Timing"] += f", db;dur={g.db_ms:.2f}"
            if hasattr(g, 'skap_db_ms'):
                response.headers["Server-Timing"] += f", skap_db;dur={g.skap_db_ms:.2f}"

        if elapsed is not None and request_metrics.should_record(request.path):
            request_metrics.record(
                request.url_rule.rule if request.url_rule else "(sin ruta)",
                request.method,
                response.status_code,
                elapsed,
                getattr(g, "db_ms", 0.0),
                getattr(g, "db_queries", 0),
            )

        user_id = session.get("user_id")
        user_role = session.get("user_role")
        app.logger.info(
            "request",
            extra={
                "extra": {
                    "path": request.path,
                    "method": request.method,
                    "status": response.status_code,
                    "ms": elapsed,
                    "db_ms": round(getattr(g, "db_ms", 0), 2),
                    "db_queries": getattr(g, "db_queries", 0),
                    "skap_db_ms": round(g.skap_db_ms, 2) if hasattr(g, "skap_db_ms") else None,
                    "skap_db_reads": getattr(g, "skap_db_reads", None),
                    "user_id": user_id,
                    "user_role": user_role,
                }
            }
        )
        return response

    @app.context_processor
    def _inject_csp_nonce():
        return {"csp_nonce": _csp_nonce}

    @app.context_processor
    def _inject_panel_notifications():
        def can_web(module, action="ver"):
            user_id = session.get("user_id")
            if not user_id:
                return False
            cache_key = f"{module}:{action}"
            if not hasattr(g, "_web_permission_cache"):
                g._web_permission_cache = {}
            if cache_key not in g._web_permission_cache:
                try:
                    from web.auth.decorators import can_access_module

                    g._web_permission_cache[cache_key] = can_access_module(user_id, module, action)
                except Exception:
                    app.logger.warning("web_permission_context_error", exc_info=True)
                    g._web_permission_cache[cache_key] = False
            return g._web_permission_cache[cache_key]

        def is_strict_admin_safe():
            try:
                from web.auth.decorators import is_strict_admin

                return bool(session.get("user_id")) and is_strict_admin()
            except Exception:
                app.logger.warning("strict_admin_context_error", exc_info=True)
                return False

        role = str(session.get("user_role") or "").strip().lower()
        if not session.get("user_id") or role not in {"admin", "rrhh"}:
            return {
                "can_web": can_web,
                "is_strict_admin": is_strict_admin_safe,
                "panel_notifications": {
                    "enabled": False,
                    "total": 0,
                    "items": [],
                    "has_items": False,
                },
                "export_toolbar": build_export_toolbar(request.endpoint),
            }

        return {
            "can_web": can_web,
            "is_strict_admin": is_strict_admin_safe,
            "panel_notifications": {"enabled": True, "total": 0, "items": [], "has_items": False},
            "export_toolbar": build_export_toolbar(request.endpoint),
        }
    
     
    return app

# ======================
# Gunicorn binding
# ======================

if os.getenv("FLASK_SKIP_APP_BOOT", "0") == "1" or __name__ == "__main__":
    app = None
else:
    app = create_app()


# ======================
# Desarrollo local
# =================
if __name__ == "__main__":
    try:
        os.environ.setdefault("APP_ENV", "development")
        app = create_app()
    except (AppConfigError, DatabaseConfigError) as exc:
        raise SystemExit(str(exc))
    debug = _app_env() == 'development' and _parse_bool_env('FLASK_DEBUG', default=False)
    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=debug)
