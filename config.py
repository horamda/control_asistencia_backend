import os
from dotenv import load_dotenv

load_dotenv()


def _env(name, default=None):
    railway_mysql_aliases = {
        "DB_HOST": "MYSQLHOST",
        "DB_PORT": "MYSQLPORT",
        "DB_USER": "MYSQLUSER",
        "DB_PASSWORD": "MYSQLPASSWORD",
        "DB_NAME": "MYSQLDATABASE",
    }
    return os.getenv(name) or os.getenv(railway_mysql_aliases.get(name, "")) or default


DB_CONFIG = {
    "host": _env("DB_HOST"),
    "port": int(_env("DB_PORT", 3306)),
    "user": _env("DB_USER"),
    "password": _env("DB_PASSWORD"),
    "database": _env("DB_NAME")
}

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_EXPIRATION_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", 60 * 60 * 8))  # 8 horas

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads/fotos")
