from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Singleton: se inicializa con limiter.init_app(app) en la factory create_app().
# La factory carga RATELIMIT_STORAGE_URI después de leer el entorno.
# El entrypoint exige almacenamiento compartido para múltiples workers.
limiter = Limiter(
    key_func=get_remote_address,
    strategy="fixed-window",
    default_limits=[],
)


def mobile_login_account_key():
    # Hash identifiers so Redis keys do not expose employee DNI values.
    import hashlib
    from flask import request
    payload = request.get_json(silent=True)
    dni = str(payload.get("dni") or "").strip() if isinstance(payload, dict) else ""
    return "mobile-login:" + hashlib.sha256(dni.encode()).hexdigest()


def failed_login(response):
    return response.status_code in (400, 401)
