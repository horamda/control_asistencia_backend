from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = "" if include_inactive else "WHERE activo = 1"
        cursor.execute(
            f"""
            SELECT *
            FROM feedback_motivos
            {where}
            ORDER BY activo DESC, nombre ASC
            """
        )
        return cursor.fetchall()
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
            where.append("(nombre LIKE %s OR descripcion LIKE %s)")
            params.extend([like, like])
        if activo in (0, 1):
            where.append("activo = %s")
            params.append(int(activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(
            f"""
            SELECT *
            FROM feedback_motivos
            {where_sql}
            ORDER BY activo DESC, nombre ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM feedback_motivos
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(motivo_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM feedback_motivos
            WHERE id = %s
            LIMIT 1
            """,
            (motivo_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_nombre(nombre: str, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if exclude_id:
            cursor.execute(
                """
                SELECT *
                FROM feedback_motivos
                WHERE LOWER(nombre) = LOWER(%s)
                  AND id <> %s
                LIMIT 1
                """,
                (str(nombre).strip(), int(exclude_id)),
            )
        else:
            cursor.execute(
                """
                SELECT *
                FROM feedback_motivos
                WHERE LOWER(nombre) = LOWER(%s)
                LIMIT 1
                """,
                (str(nombre).strip(),),
            )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO feedback_motivos (nombre, descripcion, sla_dias, activo)
            VALUES (%s, %s, %s, %s)
            """,
            (
                data.get("nombre"),
                data.get("descripcion"),
                int(data.get("sla_dias") or 1),
                1 if data.get("activo", True) else 0,
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(motivo_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedback_motivos
            SET nombre = %s,
                descripcion = %s,
                sla_dias = %s,
                activo = %s
            WHERE id = %s
            """,
            (
                data.get("nombre"),
                data.get("descripcion"),
                int(data.get("sla_dias") or 1),
                1 if data.get("activo", True) else 0,
                motivo_id,
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(motivo_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedback_motivos
            SET activo = %s
            WHERE id = %s
            """,
            (1 if activo else 0, motivo_id),
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
            FROM feedback_motivos
            {where}
            """
        )
        return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        cursor.close()
        db.close()


def get_active_for_select():
    return get_all(include_inactive=False)
