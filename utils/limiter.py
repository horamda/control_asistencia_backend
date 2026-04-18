from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Singleton: se inicializa con limiter.init_app(app) en la factory create_app().
# Almacenamiento en memoria (no requiere Redis).
# Para producción con múltiples workers usar storage_uri="redis://localhost:6379/0".
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    strategy="fixed-window",
    default_limits=[],
)
