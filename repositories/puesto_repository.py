from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT p.*, e.razon_social AS empresa_nombre
                FROM puestos p
                JOIN empresas e ON e.id = p.empresa_id
                ORDER BY e.razon_social, p.nombre
            """)
        else:
            cursor.execute("""
                SELECT p.*, e.razon_social AS empresa_nombre
                FROM puestos p
                JOIN empresas e ON e.id = p.empresa_id
                WHERE p.activo = 1
                ORDER BY e.razon_social, p.nombre
            """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(page: int, per_page: int, empresa_id: int | None = None, search: str | None = None, activo: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if empresa_id:
            where.append("p.empresa_id = %s")
            params.append(empresa_id)
        if activo is not None:
            where.append("p.activo = %s")
            params.append(activo)
        if search:
            where.append("p.nombre LIKE %s")
            params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"""
            SELECT p.*, e.razon_social AS empresa_nombre
            FROM puestos p
            JOIN empresas e ON e.id = p.empresa_id
            {where_sql}
            ORDER BY e.razon_social, p.nombre
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total FROM puestos p {where_sql}", params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(puesto_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM puestos
            WHERE id = %s
        """, (puesto_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO puestos (empresa_id, nombre, activo)
            VALUES (%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            1 if data.get("activo") else 0
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(puesto_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE puestos
            SET empresa_id = %s,
                nombre = %s,
                activo = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            1 if data.get("activo") else 0,
            puesto_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(puesto_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE puestos
            SET activo = %s
            WHERE id = %s
        """, (1 if activo else 0, puesto_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
