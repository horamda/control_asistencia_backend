from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT *
                FROM empresas
                ORDER BY razon_social
            """)
        else:
            cursor.execute("""
                SELECT *
                FROM empresas
                WHERE activa = 1
                ORDER BY razon_social
            """)
        rows = cursor.fetchall()
        return rows
    finally:
        cursor.close()
        db.close()


def get_by_id(empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM empresas
            WHERE id = %s
        """, (empresa_id,))
        emp = cursor.fetchone()
        return emp
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO empresas
            (
                razon_social,
                nombre_fantasia,
                cuit,
                logo,
                email,
                telefono,
                direccion,
                activa
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.get("razon_social"),
            data.get("nombre_fantasia"),
            data.get("cuit"),
            data.get("logo"),
            data.get("email"),
            data.get("telefono"),
            data.get("direccion"),
            1 if data.get("activa") else 0
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(empresa_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE empresas
            SET
                razon_social = %s,
                nombre_fantasia = %s,
                cuit = %s,
                logo = %s,
                email = %s,
                telefono = %s,
                direccion = %s,
                activa = %s
            WHERE id = %s
        """, (
            data.get("razon_social"),
            data.get("nombre_fantasia"),
            data.get("cuit"),
            data.get("logo"),
            data.get("email"),
            data.get("telefono"),
            data.get("direccion"),
            1 if data.get("activa") else 0,
            empresa_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activa(empresa_id: int, activa: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE empresas
            SET activa = %s
            WHERE id = %s
        """, (1 if activa else 0, empresa_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
