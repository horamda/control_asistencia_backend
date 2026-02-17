from extensions import get_db


def has_role(actor_id, role_name):
    conn = get_db()
    user_cur = conn.cursor(dictionary=True)
    legacy_cur = None
    try:
        # Modelo actual: usuarios.rol (admin/rrhh/supervisor).
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
            expected = str(role_name or "").strip().lower()
            return user_role == expected or user_role == "admin"

        # Fallback legacy: empleado_roles.
        legacy_cur = conn.cursor()
        legacy_cur.execute("""
            SELECT 1
            FROM empleado_roles er
            JOIN roles r ON r.id = er.rol_id
            WHERE er.empleado_id = %s
              AND LOWER(r.nombre) = %s
            LIMIT 1
        """, (actor_id, str(role_name or "").strip().lower()))

        ok = legacy_cur.fetchone() is not None
        return ok
    finally:
        user_cur.close()
        if legacy_cur is not None:
            legacy_cur.close()
        conn.close()


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
