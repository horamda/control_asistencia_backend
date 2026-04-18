"""
Configuración global de pytest.

Setea variables de entorno mínimas antes de que cualquier módulo
del proyecto sea importado, evitando que init_db() falle al
levantar los tests que usan monkeypatch para mock.
"""
import os

# Evita que app.py ejecute create_app() a nivel de módulo
os.environ.setdefault("FLASK_SKIP_APP_BOOT", "1")

# Variables de DB requeridas por db.py para construir la URI
# (los tests que usan monkeypatch nunca llegan a conectarse)
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

os.environ.setdefault("JWT_SECRET", "test_jwt_secret_0123456789abcdef_pytest")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test_flask_secret_0123456789abcdef")
