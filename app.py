from flask import Flask, redirect, url_for, request, jsonify, render_template, session
from flask_cors import CORS
from dotenv import load_dotenv
import os
import logging
import json
import time
from flask_wtf.csrf import CSRFProtect
from werkzeug.exceptions import HTTPException

from extensions import init_db
from routes.auth_routes import auth_bp          # API
from routes.mobile_v1_routes import mobile_v1_bp
from routes.media_routes import media_bp
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
from web.empleado_excepciones.empleado_excepciones_routes import empleado_excepciones_bp
from web.qr_puerta.qr_puerta_routes import qr_puerta_bp
from web.legajos.legajos_routes import legajos_bp

load_dotenv()

def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret")

    CORS(app)

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
    app.register_blueprint(empleado_excepciones_bp)
    app.register_blueprint(qr_puerta_bp)
    app.register_blueprint(legajos_bp)

    @app.route("/")
    def index():
        return redirect(url_for("web_auth.login"))

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

app = create_app()


# ======================
# Desarrollo local
# ======================


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
