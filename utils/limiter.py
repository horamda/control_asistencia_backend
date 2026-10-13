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
