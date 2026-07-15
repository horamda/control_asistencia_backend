from __future__ import annotations

from extensions import get_db

# puesto_filter: None => sin filtro; 0 => solo generales (puesto_id IS NULL); N>0 => ese puesto exacto
_PUESTO_GENERAL = 0


def _build_where(
    *,
    search: str | None = None,
    sector_id: int | None = None,
    puesto_filter: int | None = None,
    categoria: str | None = None,
    activo: int | None = None,
):
    where = []
    params: list = []

    if search:
        like = f"%{search}%"
        where.append("(q.descripcion LIKE %s OR s.nombre LIKE %s)")
        params.extend([like, like])
    if sector_id:
        where.append("q.sector_id = %s")
        params.append(int(sector_id))
    if puesto_filter is not None:
        if int(puesto_filter) == _PUESTO_GENERAL:
            where.append("q.puesto_id IS NULL")
        else:
            where.append("q.puesto_id = %s")
            params.append(int(puesto_filter))
    if categoria:
        where.append("q.categoria = %s")
        params.append(str(categoria).strip().upper())
    if activo in (0, 1):
        where.append("q.activo = %s")
        params.append(int(activo))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def get_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    sector_id: int | None = None,
    puesto_filter: int | None = None,
    categoria: str | None = None,
    activo: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_where(
            search=search,
            sector_id=sector_id,
            puesto_filter=puesto_filter,
            categoria=categoria,
            activo=activo,
        )
        offset = max(0, (int(page) - 1) * int(per_page))
        cursor.execute(
            f"""
            SELECT
                q.*,
                s.nombre AS sector_nombre,
                p.nombre AS puesto_nombre
            FROM skap_preguntas q
            JOIN sectores s ON s.id = q.sector_id
            LEFT JOIN puestos p ON p.id = q.puesto_id
            {where_sql}
            ORDER BY q.activo DESC, s.nombre ASC, p.nombre ASC, q.categoria ASC, q.peso DESC, q.descripcion ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall() or []

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM skap_preguntas q
            JOIN sectores s ON s.id = q.sector_id
            LEFT JOIN puestos p ON p.id = q.puesto_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_all_active_for_sector(
    sector_id: int,
    *,
    puesto_id: int | None = None,
    categoria: str | None = None,
    activo: int | None = 1,
):
    """Preguntas activas de un sector, incluyendo generales (puesto_id NULL)
    y, si se indica puesto_id, tambien las especificas de ese puesto."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["q.sector_id = %s"]
        params: list = [int(sector_id)]
        if activo in (0, 1):
            where.append("q.activo = %s")
            params.append(int(activo))
        if puesto_id:
            where.append("(q.puesto_id IS NULL OR q.puesto_id = %s)")
            params.append(int(puesto_id))
        else:
            where.append("q.puesto_id IS NULL")
        if categoria:
            where.append("q.categoria = %s")
            params.append(str(categoria).strip().upper())
        cursor.execute(
            f"""
            SELECT
                q.*,
                s.nombre AS sector_nombre,
                p.nombre AS puesto_nombre
            FROM skap_preguntas q
            JOIN sectores s ON s.id = q.sector_id
            LEFT JOIN puestos p ON p.id = q.puesto_id
            WHERE {" AND ".join(where)}
            ORDER BY q.categoria ASC, q.peso DESC, q.descripcion ASC
            """,
            tuple(params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_by_id(pregunta_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                q.*,
                s.nombre AS sector_nombre,
                p.nombre AS puesto_nombre
            FROM skap_preguntas q
            JOIN sectores s ON s.id = q.sector_id
            LEFT JOIN puestos p ON p.id = q.puesto_id
            WHERE q.id = %s
            LIMIT 1
            """,
            (pregunta_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_unique(
    sector_id: int,
    categoria: str,
    descripcion: str,
    *,
    puesto_id: int | None = None,
    exclude_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        params = [int(sector_id), str(categoria).strip().upper(), str(descripcion).strip()]
        sql = """
            SELECT *
            FROM skap_preguntas
            WHERE sector_id = %s
              AND categoria = %s
              AND LOWER(descripcion) = LOWER(%s)
              AND puesto_id <=> %s
        """
        params.append(int(puesto_id) if puesto_id else None)
        if exclude_id:
            sql += " AND id <> %s"
            params.append(int(exclude_id))
        sql += " LIMIT 1"
        cursor.execute(sql, tuple(params))
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
            INSERT INTO skap_preguntas
            (
                sector_id,
                puesto_id,
                categoria,
                descripcion,
                peso,
                puntaje_esperado,
                requiere_observacion,
                requiere_evidencia,
                activo
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("sector_id"),
                data.get("puesto_id") or None,
                str(data.get("categoria") or "").strip().upper(),
                data.get("descripcion"),
                data.get("peso"),
                data.get("puntaje_esperado"),
                1 if data.get("requiere_observacion") else 0,
                1 if data.get("requiere_evidencia") else 0,
                1 if data.get("activo", True) else 0,
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(pregunta_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_preguntas
            SET sector_id = %s,
                puesto_id = %s,
                categoria = %s,
                descripcion = %s,
                peso = %s,
                puntaje_esperado = %s,
                requiere_observacion = %s,
                requiere_evidencia = %s,
                activo = %s
            WHERE id = %s
            """,
            (
                data.get("sector_id"),
                data.get("puesto_id") or None,
                str(data.get("categoria") or "").strip().upper(),
                data.get("descripcion"),
                data.get("peso"),
                data.get("puntaje_esperado"),
                1 if data.get("requiere_observacion") else 0,
                1 if data.get("requiere_evidencia") else 0,
                1 if data.get("activo", True) else 0,
                pregunta_id,
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(pregunta_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_preguntas
            SET activo = %s
            WHERE id = %s
            """,
            (1 if activo else 0, pregunta_id),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def count_all(*, activo: int | None = None) -> int:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ""
        params: list = []
        if activo in (0, 1):
            where = "WHERE activo = %s"
            params.append(int(activo))
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM skap_preguntas
            {where}
            """,
            tuple(params),
        )
        return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        cursor.close()
        db.close()
