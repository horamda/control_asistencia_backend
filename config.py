import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_EXPIRATION_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", 60 * 60 * 8))  # 8 horas

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads/fotos")
