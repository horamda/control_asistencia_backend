"""API local de consulta de presencia, sin tareas programadas ni migraciones."""

from flask import Flask

from db import init_orm
from web.presencia_routes import presencia_bp


if __name__ == "__main__":
    init_orm()
    app = Flask(__name__)
    app.register_blueprint(presencia_bp)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
