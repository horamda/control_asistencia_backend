from extensions import get_db
from utils.search import build_tokenized_like_clause, normalize_search_terms


_FEEDBACK_CLIENTE_SEARCH_FIELDS = (
    "id",
    "codigo_externo",
    "razon_social",
    "nombre_fantasia",
    "telefonos",
    "movil",
    "email",
    "domicilio",
    "localidad",
    "descripcion_localidad",
    "provincia",
    "descripcion_provincia",
    "tipo_codigo",
    "tipo_descripcion",
)


def _norm_sql(column: str) -> str:
    return f"LOWER(TRIM(COALESCE({column}, '')))"


def _normalize_search_query(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _row_value(row: dict, field: str) -> str:
    return _normalize_search_query(row.get(field))


def _feedback_cliente_matches_search(row: dict, search: str | None) -> bool:
    terms = normalize_search_terms(search, max_terms=6)
    if not terms:
        return True

    searchable_values = [_row_value(row, field) for field in _FEEDBACK_CLIENTE_SEARCH_FIELDS]
    return all(
        any(term in value for value in searchable_values)
        for term in terms
    )


def _feedback_cliente_search_rank(row: dict, search: str | None) -> int | None:
    phrase = _normalize_search_query(search)
    if not phrase:
        return 0

    if not _feedback_cliente_matches_search(row, phrase):
        return None

    codigo = _row_value(row, "codigo_externo")
    cliente_id = _row_value(row, "id")
    razon_social = _row_value(row, "razon_social")
    nombre_fantasia = _row_value(row, "nombre_fantasia")

    if codigo == phrase or cliente_id == phrase:
        return 0
    if codigo.startswith(phrase) or cliente_id.startswith(phrase):
        return 1
    if razon_social == phrase or nombre_fantasia == phrase:
        return 2
    if razon_social.startswith(phrase) or nombre_fantasia.startswith(phrase):
        return 3
    if phrase in codigo or phrase in razon_social or phrase in nombre_fantasia:
        return 4
    return 5


def _feedback_cliente_ranked_rows(rows: list[dict], search: str | None) -> list[dict]:
    phrase = _normalize_search_query(search)
    if not phrase:
        return list(rows)

    ranked_rows = []
    for index, row in enumerate(rows):
        rank = _feedback_cliente_search_rank(row, phrase)
        if rank is None:
            continue
        ranked_rows.append(
            (
                rank,
                _row_value(row, "razon_social"),
                _row_value(row, "codigo_externo"),
                index,
                row,
            )
        )

    ranked_rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [row for _, _, _, _, row in ranked_rows]


def _build_feedback_cliente_rank_sql(search: str | None) -> tuple[str, tuple[str, ...]]:
    phrase = _normalize_search_query(search)
    if not phrase:
        return "", ()

    prefix = f"{phrase}%"
    like = f"%{phrase}%"

    sql = f"""
    CASE
        WHEN {_norm_sql('codigo_externo')} = %s OR {_norm_sql('CAST(id AS CHAR)')} = %s THEN 0
        WHEN {_norm_sql('codigo_externo')} LIKE %s OR {_norm_sql('CAST(id AS CHAR)')} LIKE %s THEN 1
        WHEN {_norm_sql('razon_social')} = %s OR {_norm_sql('nombre_fantasia')} = %s THEN 2
        WHEN {_norm_sql('razon_social')} LIKE %s OR {_norm_sql('nombre_fantasia')} LIKE %s THEN 3
        WHEN {_norm_sql('razon_social')} LIKE %s OR {_norm_sql('nombre_fantasia')} LIKE %s OR {_norm_sql('codigo_externo')} LIKE %s THEN 4
        WHEN {_norm_sql('telefonos')} LIKE %s OR {_norm_sql('movil')} LIKE %s OR {_norm_sql('email')} LIKE %s OR {_norm_sql('domicilio')} LIKE %s OR {_norm_sql('localidad')} LIKE %s OR {_norm_sql('descripcion_localidad')} LIKE %s OR {_norm_sql('provincia')} LIKE %s OR {_norm_sql('descripcion_provincia')} LIKE %s OR {_norm_sql('tipo_codigo')} LIKE %s OR {_norm_sql('tipo_descripcion')} LIKE %s THEN 5
        ELSE 99
    END
    """.strip()

    params = (
        phrase,
        phrase,
        prefix,
        prefix,
        phrase,
        phrase,
        prefix,
        prefix,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
    )
    return sql, params


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
            clause, clause_params = build_tokenized_like_clause(
                [
                    _norm_sql("CAST(id AS CHAR)"),
                    _norm_sql("CAST(sucursal_origen AS CHAR)"),
                    _norm_sql("codigo_externo"),
                    _norm_sql("razon_social"),
                    _norm_sql("nombre_fantasia"),
                    _norm_sql("telefonos"),
                    _norm_sql("movil"),
                    _norm_sql("email"),
                    _norm_sql("domicilio"),
                    _norm_sql("localidad"),
                    _norm_sql("descripcion_localidad"),
                    _norm_sql("provincia"),
                    _norm_sql("descripcion_provincia"),
                    _norm_sql("tipo_codigo"),
                    _norm_sql("tipo_descripcion"),
                ],
                _normalize_search_query(search),
                max_terms=6,
            )
            if clause:
                where.append(clause)
                params.extend(clause_params)
        if activo in (0, 1):
            where.append("activo = %s")
            params.append(int(activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rank_sql, rank_params = _build_feedback_cliente_rank_sql(search)
        order_sql = "ORDER BY razon_social ASC, codigo_externo ASC"
        if rank_sql:
            order_sql = f"ORDER BY {rank_sql}, razon_social ASC, codigo_externo ASC"

        try:
            cursor.execute(
                f"""
                SELECT *
                FROM feedback_clientes
                {where_sql}
                {order_sql}
                LIMIT %s OFFSET %s
                """,
                (*params, *rank_params, int(per_page), offset),
            )
            rows = cursor.fetchall()
        except Exception:
            if not search:
                raise
            return _get_page_python_fallback(
                cursor,
                page=int(page),
                per_page=int(per_page),
                search=search,
                activo=activo,
            )
        if search and not rows:
            return _get_page_python_fallback(
                cursor,
                page=int(page),
                per_page=int(per_page),
                search=search,
                activo=activo,
            )

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


def _get_page_python_fallback(
    cursor,
    *,
    page: int,
    per_page: int,
    search: str | None,
    activo: int | None,
) -> tuple[list[dict], int]:
    where = []
    params = []
    if activo in (0, 1):
        where.append("activo = %s")
        params.append(int(activo))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    cursor.execute(
        f"""
        SELECT *
        FROM feedback_clientes
        {where_sql}
        """,
        tuple(params),
    )
    ranked = _feedback_cliente_ranked_rows(cursor.fetchall(), search)
    total = len(ranked)
    offset = max(0, (int(page) - 1) * int(per_page))
    return ranked[offset: offset + int(per_page)], total


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
