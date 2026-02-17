from extensions import get_db
from werkzeug.security import check_password_hash


def authenticate_user(dni, password):
    conn = get_db()
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

    cursor.close()
    conn.close()

    if not user:
        return None, "Usuario no encontrado"

    if not user["activo"]:
        return None, "Usuario inactivo"

    if not user.get("password_hash"):
        return None, "Contrasena no configurada"

    if not check_password_hash(user["password_hash"], password):
        return None, "Contrasena incorrecta"

    return user, None
