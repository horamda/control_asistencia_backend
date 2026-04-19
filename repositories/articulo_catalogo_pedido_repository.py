from extensions import get_db


def get_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    habilitado_only: bool = True,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = []
        params = []

        if habilitado_only:
            where.append("a.habilitado_pedido = 1")
        if search:
            like = f"%{search}%"
            where.append(
                "(a.codigo_articulo LIKE %s OR a.descripcion LIKE %s OR a.marca LIKE %s OR a.familia LIKE %s OR a.sabor LIKE %s)"
            )
            params.extend([like, like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(
            f"""
            SELECT
                a.*
            FROM articulos_catalogo_pedidos a
            {where_sql}
            ORDER BY a.descripcion, a.codigo_articulo
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM articulos_catalogo_pedidos a
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_ids(articulo_ids: list[int], *, habilitado_only: bool = True):
    if not articulo_ids:
        return []

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        placeholders = ",".join(["%s"] * len(articulo_ids))
        where = [f"a.id IN ({placeholders})"]
        params = [int(articulo_id) for articulo_id in articulo_ids]
        if habilitado_only:
            where.append("a.habilitado_pedido = 1")

        cursor.execute(
            f"""
            SELECT
                a.*
            FROM articulos_catalogo_pedidos a
            WHERE {" AND ".join(where)}
            ORDER BY a.descripcion, a.codigo_articulo
            """,
            tuple(params),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()
