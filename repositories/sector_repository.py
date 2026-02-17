from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT s.*, e.razon_social AS empresa_nombre
                FROM sectores s
                JOIN empresas e ON e.id = s.empresa_id
                ORDER BY e.razon_social, s.nombre
            """)
        else:
            cursor.execute("""
                SELECT s.*, e.razon_social AS empresa_nombre
                FROM sectores s
                JOIN empresas e ON e.id = s.empresa_id
                WHERE s.activo = 1
                ORDER BY e.razon_social, s.nombre
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
            where.append("s.empresa_id = %s")
            params.append(empresa_id)
        if activo is not None:
            where.append("s.activo = %s")
            params.append(activo)
        if search:
            where.append("s.nombre LIKE %s")
            params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"""
            SELECT s.*, e.razon_social AS empresa_nombre
            FROM sectores s
            JOIN empresas e ON e.id = s.empresa_id
            {where_sql}
            ORDER BY e.razon_social, s.nombre
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total FROM sectores s {where_sql}", params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(sector_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM sectores
            WHERE id = %s
        """, (sector_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO sectores (empresa_id, nombre, activo)
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


def update(sector_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE sectores
            SET empresa_id = %s,
                nombre = %s,
                activo = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            1 if data.get("activo") else 0,
            sector_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(sector_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE sectores
            SET activo = %s
            WHERE id = %s
        """, (1 if activo else 0, sector_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
