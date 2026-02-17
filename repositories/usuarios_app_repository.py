from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT u.*, e.razon_social AS empresa_nombre
                FROM usuarios u
                JOIN empresas e ON e.id = u.empresa_id
                ORDER BY e.razon_social, u.usuario
            """)
        else:
            cursor.execute("""
                SELECT u.*, e.razon_social AS empresa_nombre
                FROM usuarios u
                JOIN empresas e ON e.id = u.empresa_id
                WHERE u.activo = 1
                ORDER BY e.razon_social, u.usuario
            """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(page: int, per_page: int, empresa_id: int | None = None, activo: int | None = None, search: str | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if empresa_id:
            where.append("u.empresa_id = %s")
            params.append(empresa_id)
        if activo is not None:
            where.append("u.activo = %s")
            params.append(activo)
        if search:
            where.append("u.usuario LIKE %s")
            params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"""
            SELECT u.*, e.razon_social AS empresa_nombre
            FROM usuarios u
            JOIN empresas e ON e.id = u.empresa_id
            {where_sql}
            ORDER BY e.razon_social, u.usuario
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM usuarios u
            {where_sql}
        """, params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def exists_unique(usuario: str, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        if exclude_id:
            cursor.execute("""
                SELECT 1
                FROM usuarios
                WHERE usuario = %s
                  AND id <> %s
                LIMIT 1
            """, (usuario, exclude_id))
        else:
            cursor.execute("""
                SELECT 1
                FROM usuarios
                WHERE usuario = %s
                LIMIT 1
            """, (usuario,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def get_by_id(user_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM usuarios
            WHERE id = %s
        """, (user_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_usuario(usuario: str, only_active: bool = True):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if only_active:
            cursor.execute(
                """
                SELECT *
                FROM usuarios
                WHERE usuario = %s
                  AND activo = 1
                LIMIT 1
                """,
                (usuario,),
            )
        else:
            cursor.execute(
                """
                SELECT *
                FROM usuarios
                WHERE usuario = %s
                LIMIT 1
                """,
                (usuario,),
            )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO usuarios
            (
                empresa_id,
                usuario,
                password_hash,
                rol,
                activo
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("usuario"),
            data.get("password_hash"),
            data.get("rol"),
            1 if data.get("activo") else 0
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(user_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE usuarios
            SET
                empresa_id = %s,
                usuario = %s,
                rol = %s,
                activo = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("usuario"),
            data.get("rol"),
            1 if data.get("activo") else 0,
            user_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def update_password(user_id: int, password_hash: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE usuarios
            SET password_hash = %s
            WHERE id = %s
        """, (password_hash, user_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(user_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE usuarios
            SET activo = %s
            WHERE id = %s
        """, (1 if activo else 0, user_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
