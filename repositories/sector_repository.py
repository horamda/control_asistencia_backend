from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql = "" if include_inactive else "WHERE s.activo = 1"
        cursor.execute(f"""
            SELECT
                s.*,
                e.razon_social AS empresa_nombre,
                sp.nombre AS sector_padre_nombre,
                r.nombre AS responsable_nombre,
                r.apellido AS responsable_apellido,
                p.nombre AS responsable_puesto_nombre
            FROM sectores s
            JOIN empresas e ON e.id = s.empresa_id
            LEFT JOIN sectores sp ON sp.id = s.sector_padre_id
            LEFT JOIN empleados r ON r.id = s.responsable_empleado_id
            LEFT JOIN puestos p ON p.id = r.puesto_id
            {where_sql}
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
            SELECT
                s.*,
                e.razon_social AS empresa_nombre,
                sp.nombre AS sector_padre_nombre,
                r.nombre AS responsable_nombre,
                r.apellido AS responsable_apellido,
                p.nombre AS responsable_puesto_nombre
            FROM sectores s
            JOIN empresas e ON e.id = s.empresa_id
            LEFT JOIN sectores sp ON sp.id = s.sector_padre_id
            LEFT JOIN empleados r ON r.id = s.responsable_empleado_id
            LEFT JOIN puestos p ON p.id = r.puesto_id
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
            INSERT INTO sectores (
                empresa_id,
                sector_padre_id,
                responsable_empleado_id,
                nombre,
                activo
            )
            VALUES (%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("sector_padre_id"),
            data.get("responsable_empleado_id"),
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
                sector_padre_id = %s,
                responsable_empleado_id = %s,
                nombre = %s,
                activo = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("sector_padre_id"),
            data.get("responsable_empleado_id"),
            data.get("nombre"),
            1 if data.get("activo") else 0,
            sector_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def would_create_cycle(sector_id: int, parent_id: int | None) -> bool:
    if not sector_id or not parent_id:
        return False
    if int(sector_id) == int(parent_id):
        return True

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        current_parent_id = int(parent_id)
        visited = {int(sector_id)}
        while current_parent_id:
            if current_parent_id in visited:
                return True
            visited.add(current_parent_id)
            cursor.execute(
                "SELECT sector_padre_id FROM sectores WHERE id = %s",
                (current_parent_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            current_parent_id = row.get("sector_padre_id")
            current_parent_id = int(current_parent_id) if current_parent_id else None
        return False
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
