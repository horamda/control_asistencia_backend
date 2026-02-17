from extensions import get_db


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM roles
            ORDER BY nombre
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(page: int, per_page: int, search: str | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = ""
        params = []
        if search:
            where = "WHERE nombre LIKE %s"
            params.append(f"%{search}%")
        cursor.execute(f"""
            SELECT *
            FROM roles
            {where}
            ORDER BY nombre
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        if search:
            cursor.execute("SELECT COUNT(*) AS total FROM roles WHERE nombre LIKE %s", (f"%{search}%",))
        else:
            cursor.execute("SELECT COUNT(*) AS total FROM roles")
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(rol_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM roles
            WHERE id = %s
        """, (rol_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(nombre: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO roles (nombre)
            VALUES (%s)
        """, (nombre,))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(rol_id: int, nombre: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE roles
            SET nombre = %s
            WHERE id = %s
        """, (nombre, rol_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(rol_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM roles
            WHERE id = %s
        """, (rol_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
