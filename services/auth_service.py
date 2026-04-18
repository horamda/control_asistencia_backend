from extensions import get_db
from werkzeug.security import check_password_hash, generate_password_hash

AUTH_INVALID_CREDENTIALS_MESSAGE = "Credenciales invalidas."
AUTH_FAILURE_NOT_FOUND = "not_found"
AUTH_FAILURE_INACTIVE = "inactive"
AUTH_FAILURE_PASSWORD_NOT_CONFIGURED = "password_not_configured"
AUTH_FAILURE_BAD_PASSWORD = "bad_password"

# Hash dummy para prevenir timing attacks: siempre ejecutamos check_password_hash,
# incluso cuando el usuario no existe, para que el tiempo de respuesta sea constante.
_DUMMY_HASH = generate_password_hash("__dummy_timing_prevention__")


def authenticate_user(dni, password):
    conn = get_db()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, dni, nombre, password_hash, activo
            FROM empleados
            WHERE dni = %s
            LIMIT 1
            """,
            (dni,),
        )
        user = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        conn.close()

    if not user:
        # Ejecutar igual para mantener tiempo de respuesta constante (timing attack)
        check_password_hash(_DUMMY_HASH, password)
        return None, AUTH_FAILURE_NOT_FOUND

    if not user["activo"]:
        check_password_hash(_DUMMY_HASH, password)
        return None, AUTH_FAILURE_INACTIVE

    if not user.get("password_hash"):
        check_password_hash(_DUMMY_HASH, password)
        return None, AUTH_FAILURE_PASSWORD_NOT_CONFIGURED

    if not check_password_hash(user["password_hash"], password):
        return None, AUTH_FAILURE_BAD_PASSWORD

    return user, None
