from extensions import get_db


def has_any_role(actor_id, role_names):
    conn = get_db()
    user_cur = conn.cursor(dictionary=True)
    try:
        # Acceso web: rol directo en tabla usuarios.
        user_cur.execute("""
            SELECT id, rol, activo
            FROM usuarios
            WHERE id = %s
            LIMIT 1
        """, (actor_id,))
        user = user_cur.fetchone()
        if user:
            if not user.get("activo"):
                return False
            user_role = (user.get("rol") or "").strip().lower()
            expected_roles = {
                str(name or "").strip().lower()
                for name in (role_names or [])
                if str(name or "").strip()
            }
            if not expected_roles:
                return True
            return user_role == "admin" or user_role in expected_roles
        return False
    finally:
        user_cur.close()
        conn.close()


def has_role(actor_id, role_name):
    return has_any_role(actor_id, [role_name])


def get_roles_by_empleado(empleado_id: int):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT r.id, r.nombre
            FROM empleado_roles er
            JOIN roles r ON r.id = er.rol_id
            WHERE er.empleado_id = %s
            ORDER BY r.nombre
        """, (empleado_id,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def set_roles_for_empleado(empleado_id: int, role_ids: list[int]):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM empleado_roles
            WHERE empleado_id = %s
        """, (empleado_id,))

        for role_id in role_ids:
            cur.execute("""
                INSERT INTO empleado_roles (empleado_id, rol_id)
                VALUES (%s,%s)
            """, (empleado_id, role_id))

        conn.commit()
        return True
    finally:
        cur.close()
        conn.close()
