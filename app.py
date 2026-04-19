from datetime import timedelta

from flask import Flask, redirect, url_for, request, jsonify, render_template, session
from flask_cors import CORS
from dotenv import load_dotenv
import os
import logging
import json
import time
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.exceptions import HTTPException
from utils.limiter import limiter

from extensions import init_db
from db import DatabaseConfigError
from routes.auth_routes import auth_bp          # API
from routes.mobile_v1_routes import mobile_v1_bp
from routes.media_routes import media_bp, public_media_bp
from web.auth.web_auth_routes import web_auth_bp  # WEB
from web.web_routes import web_bp
from web.empleados.empleados_routes import empleados_bp
from web.empresas.empresas_routes import empresas_bp
from web.sucursales.sucursales_routes import sucursales_bp
from web.horarios.horarios_routes import horarios_bp
from web.roles.roles_routes import roles_bp
from web.roles.empleado_roles_routes import empleado_roles_bp
from web.empleado_horarios.empleado_horarios_routes import empleado_horarios_bp
from web.asistencias.asistencias_routes import asistencias_bp
from web.justificaciones.justificaciones_routes import justificaciones_bp
from web.auditoria.auditoria_routes import auditoria_bp
from web.usuarios.usuarios_routes import usuarios_bp
from web.configuracion.configuracion_empresa_routes import configuracion_bp
from web.sectores.sectores_routes import sectores_bp
from web.puestos.puestos_routes import puestos_bp
from web.localidades.localidades_routes import localidades_bp
from web.francos.francos_routes import francos_bp
from web.vacaciones.vacaciones_routes import vacaciones_bp
from web.adelantos.adelantos_routes import adelantos_bp
from web.pedidos_mercaderia.pedidos_mercaderia_routes import pedidos_mercaderia_bp
from web.empleado_excepciones.empleado_excepciones_routes import empleado_excepciones_bp
from web.qr_puerta.qr_puerta_routes import qr_puerta_bp
from web.legajos.legajos_routes import legajos_bp
from web.legajos.legajo_tipos_evento_routes import legajo_tipos_evento_bp

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
        "SECRET_KEY": _require_secret_key(),
        "SESSION_COOKIE_NAME": session_cookie_name,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": session_cookie_samesite,
        "SESSION_COOKIE_SECURE": session_cookie_secure,
        "PERMANENT_SESSION_LIFETIME": timedelta(minutes=session_lifetime_minutes),
        "SESSION_REFRESH_EACH_REQUEST": False,
    }


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    app.config.update(_build_security_config())

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
        allow_headers=["Authorization", "Content-Type"],
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

    # Security
    csrf = CSRFProtect(app)
    csrf.exempt(auth_bp)
    csrf.exempt(mobile_v1_bp)

    # API
    app.register_blueprint(auth_bp)
    app.register_blueprint(mobile_v1_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(public_media_bp)

    # PANEL WEB
    app.register_blueprint(web_auth_bp)
    app.register_blueprint(web_bp)
    
    app.register_blueprint(empleados_bp)
    app.register_blueprint(empresas_bp)
    app.register_blueprint(sucursales_bp)
    app.register_blueprint(horarios_bp)
    app.register_blueprint(roles_bp)
    app.register_blueprint(empleado_roles_bp)
    app.register_blueprint(empleado_horarios_bp)
    app.register_blueprint(asistencias_bp)
    app.register_blueprint(justificaciones_bp)
    app.register_blueprint(auditoria_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(configuracion_bp)
    app.register_blueprint(sectores_bp)
    app.register_blueprint(puestos_bp)
    app.register_blueprint(localidades_bp)
    app.register_blueprint(francos_bp)
    app.register_blueprint(vacaciones_bp)
    app.register_blueprint(adelantos_bp)
    app.register_blueprint(pedidos_mercaderia_bp)
    app.register_blueprint(empleado_excepciones_bp)
    app.register_blueprint(qr_puerta_bp)
    app.register_blueprint(legajos_bp)
    app.register_blueprint(legajo_tipos_evento_bp)

    @app.route("/")
    def index():
        return redirect(url_for("web_auth.login"))

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

        if request.blueprint in {"auth", "mobile_v1"}:
            return jsonify({
                "success": False,
                "error": message
            }), code

        return render_template("error.html", code=code, message=message), code

    @app.before_request
    def _start_timer():
        request._start_time = time.time()

    @app.after_request
    def _add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
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
                    "user_id": user_id,
                    "user_role": user_role,
                }
            }
        )
        return response
    
     
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
# ======================


if __name__ == "__main__":
    try:
        os.environ.setdefault("APP_ENV", "development")
        app = create_app()
    except (AppConfigError, DatabaseConfigError) as exc:
        raise SystemExit(str(exc))
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
