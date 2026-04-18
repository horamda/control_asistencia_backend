from werkzeug.security import check_password_hash, generate_password_hash

from repositories.usuarios_app_repository import get_by_usuario

# Hash dummy para prevenir timing attacks al buscar usuarios inexistentes.
_DUMMY_HASH = generate_password_hash("__dummy_timing_prevention__")


def authenticate_admin(username: str, password: str):
    """
    Autenticacion web usando tabla usuarios.
    """
    user = get_by_usuario(username, only_active=True)
    if not user:
        check_password_hash(_DUMMY_HASH, password)
        return None

    if not user.get("password_hash"):
        check_password_hash(_DUMMY_HASH, password)
        return None

    if not check_password_hash(user["password_hash"], password):
        return None

    return user
