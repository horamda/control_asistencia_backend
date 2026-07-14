from extensions import get_db
from utils.search import build_tokenized_like_clause


def count_all(*, habilitado_only: bool = False) -> int:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql = "WHERE habilitado_pedido = 1" if habilitado_only else ""
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM articulos_catalogo_pedidos
            {where_sql}
            """
        )
        return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        cursor.close()
        db.close()


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
            clause, clause_params = build_tokenized_like_clause(
                [
                    "CAST(a.id AS CHAR)",
                    "a.codigo_articulo",
                    "a.descripcion",
                    "a.marca",
                    "a.familia",
                    "a.sabor",
                    "a.division",
                    "a.codigo_barras",
                    "a.codigo_barras_unidad",
                    "a.presentacion_bulto",
                    "a.descripcion_presentacion_bulto",
                    "a.presentacion_unidad",
                    "a.descripcion_presentacion_unidad",
                    "CAST(a.unidades_por_bulto AS CHAR)",
                    "CAST(a.bultos_por_pallet AS CHAR)",
                    "a.tipo_producto_fuente",
                ],
                search,
                max_terms=5,
            )
            if clause:
                where.append(clause)
                params.extend(clause_params)

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
