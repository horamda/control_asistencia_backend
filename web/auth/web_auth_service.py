from werkzeug.security import check_password_hash

from repositories.usuarios_app_repository import get_by_usuario


def authenticate_admin(username: str, password: str):
    """
    Autenticacion web usando tabla usuarios.
    """
    user = get_by_usuario(username, only_active=True)
    if not user:
        return None

    if not user.get("password_hash"):
        return None

    if not check_password_hash(user["password_hash"], password):
        return None

    return user
