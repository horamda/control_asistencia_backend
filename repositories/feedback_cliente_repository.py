from extensions import get_db


def get_by_id(cliente_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM feedback_clientes
            WHERE id = %s
            LIMIT 1
            """,
            (cliente_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_codigo(sucursal_origen, codigo_externo: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM feedback_clientes
            WHERE codigo_externo = %s
              AND (
                  (sucursal_origen IS NULL AND %s IS NULL)
                  OR sucursal_origen = %s
              )
            LIMIT 1
            """,
            (str(codigo_externo).strip(), sucursal_origen, sucursal_origen),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    activo: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = []
        params = []
        if search:
            like = f"%{search}%"
            where.append(
                "("
                "codigo_externo LIKE %s OR razon_social LIKE %s OR nombre_fantasia LIKE %s OR "
                "tipo_descripcion LIKE %s OR localidad LIKE %s OR provincia LIKE %s"
                ")"
            )
            params.extend([like, like, like, like, like, like])
        if activo in (0, 1):
            where.append("activo = %s")
            params.append(int(activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(
            f"""
            SELECT *
            FROM feedback_clientes
            {where_sql}
            ORDER BY razon_social ASC, codigo_externo ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM feedback_clientes
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def search(q: str | None = None, *, limit: int = 25):
    rows, _ = get_page(1, max(1, limit), search=q, activo=1)
    return rows


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO feedback_clientes
            (
                sucursal_origen,
                codigo_externo,
                razon_social,
                nombre_fantasia,
                telefonos,
                movil,
                email,
                domicilio,
                localidad,
                descripcion_localidad,
                provincia,
                descripcion_provincia,
                tipo_codigo,
                tipo_descripcion,
                comentario,
                latitud,
                longitud,
                activo
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("sucursal_origen"),
                data.get("codigo_externo"),
                data.get("razon_social"),
                data.get("nombre_fantasia"),
                data.get("telefonos"),
                data.get("movil"),
                data.get("email"),
                data.get("domicilio"),
                data.get("localidad"),
                data.get("descripcion_localidad"),
                data.get("provincia"),
                data.get("descripcion_provincia"),
                data.get("tipo_codigo"),
                data.get("tipo_descripcion"),
                data.get("comentario"),
                data.get("latitud"),
                data.get("longitud"),
                1 if data.get("activo", True) else 0,
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(cliente_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedback_clientes
            SET sucursal_origen = %s,
                codigo_externo = %s,
                razon_social = %s,
                nombre_fantasia = %s,
                telefonos = %s,
                movil = %s,
                email = %s,
                domicilio = %s,
                localidad = %s,
                descripcion_localidad = %s,
                provincia = %s,
                descripcion_provincia = %s,
                tipo_codigo = %s,
                tipo_descripcion = %s,
                comentario = %s,
                latitud = %s,
                longitud = %s,
                activo = %s
            WHERE id = %s
            """,
            (
                data.get("sucursal_origen"),
                data.get("codigo_externo"),
                data.get("razon_social"),
                data.get("nombre_fantasia"),
                data.get("telefonos"),
                data.get("movil"),
                data.get("email"),
                data.get("domicilio"),
                data.get("localidad"),
                data.get("descripcion_localidad"),
                data.get("provincia"),
                data.get("descripcion_provincia"),
                data.get("tipo_codigo"),
                data.get("tipo_descripcion"),
                data.get("comentario"),
                data.get("latitud"),
                data.get("longitud"),
                1 if data.get("activo", True) else 0,
                cliente_id,
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def upsert(data: dict):
    existing = get_by_codigo(data.get("sucursal_origen"), data.get("codigo_externo"))
    if existing:
        update(existing["id"], data)
        return existing["id"], False
    return create(data), True


def set_activo(cliente_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedback_clientes
            SET activo = %s
            WHERE id = %s
            """,
            (1 if activo else 0, cliente_id),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def count_all(include_inactive: bool = False) -> int:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = "" if include_inactive else "WHERE activo = 1"
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM feedback_clientes
            {where}
            """
        )
        return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        cursor.close()
        db.close()
