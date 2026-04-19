from extensions import get_db


_ITEMS_SUMMARY_JOIN = """
LEFT JOIN (
    SELECT
        pedido_id,
        COUNT(*) AS cantidad_items,
        COALESCE(SUM(cantidad_bultos), 0) AS total_bultos
    FROM pedidos_mercaderia_items
    GROUP BY pedido_id
) pi ON pi.pedido_id = p.id
"""


def _base_select():
    return f"""
        SELECT
            p.*,
            e.nombre,
            e.apellido,
            e.dni,
            emp.razon_social AS empresa_nombre,
            u.usuario AS resuelto_by_usuario,
            COALESCE(pi.cantidad_items, 0) AS cantidad_items,
            COALESCE(pi.total_bultos, 0) AS total_bultos
        FROM pedidos_mercaderia p
        JOIN empleados e ON e.id = p.empleado_id
        JOIN empresas emp ON emp.id = p.empresa_id
        LEFT JOIN usuarios u ON u.id = p.resuelto_by_usuario_id
        {_ITEMS_SUMMARY_JOIN}
    """


def _get_items(cursor, pedido_id: int):
    cursor.execute(
        """
        SELECT
            i.id,
            i.pedido_id,
            i.articulo_id,
            i.cantidad_bultos,
            i.codigo_articulo_snapshot,
            i.descripcion_snapshot,
            i.unidades_por_bulto_snapshot
        FROM pedidos_mercaderia_items i
        WHERE i.pedido_id = %s
        ORDER BY i.descripcion_snapshot, i.codigo_articulo_snapshot
        """,
        (pedido_id,),
    )
    return cursor.fetchall()


def _attach_items(cursor, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows

    pedido_ids = [int(row["id"]) for row in rows]
    placeholders = ",".join(["%s"] * len(pedido_ids))
    cursor.execute(
        f"""
        SELECT
            i.id,
            i.pedido_id,
            i.articulo_id,
            i.cantidad_bultos,
            i.codigo_articulo_snapshot,
            i.descripcion_snapshot,
            i.unidades_por_bulto_snapshot
        FROM pedidos_mercaderia_items i
        WHERE i.pedido_id IN ({placeholders})
        ORDER BY i.pedido_id, i.descripcion_snapshot, i.codigo_articulo_snapshot
        """,
        tuple(pedido_ids),
    )
    items_by_pedido = {}
    for item in cursor.fetchall():
        items_by_pedido.setdefault(int(item["pedido_id"]), []).append(item)

    for row in rows:
        row["items"] = items_by_pedido.get(int(row["id"]), [])
    return rows


def get_by_id(pedido_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_base_select()}
            WHERE p.id = %s
            LIMIT 1
            """,
            (pedido_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        row["items"] = _get_items(cursor, pedido_id)
        return row
    finally:
        cursor.close()
        db.close()


def get_by_empleado_periodo(empleado_id: int, periodo_year: int, periodo_month: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_base_select()}
            WHERE p.empleado_id = %s
              AND p.periodo_year = %s
              AND p.periodo_month = %s
            LIMIT 1
            """,
            (empleado_id, periodo_year, periodo_month),
        )
        row = cursor.fetchone()
        if not row:
            return None
        row["items"] = _get_items(cursor, int(row["id"]))
        return row
    finally:
        cursor.close()
        db.close()


def get_page_by_empleado(
    empleado_id: int,
    page: int,
    per_page: int,
    *,
    estado: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = ["p.empleado_id = %s"]
        params = [int(empleado_id)]
        if estado:
            where.append("p.estado = %s")
            params.append(estado)
        where_sql = "WHERE " + " AND ".join(where)

        cursor.execute(
            f"""
            {_base_select()}
            {where_sql}
            ORDER BY p.periodo_year DESC, p.periodo_month DESC, p.created_at DESC, p.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = _attach_items(cursor, cursor.fetchall())

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM pedidos_mercaderia p
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def _build_admin_filters(
    *,
    empleado_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
):
    where = []
    params = []

    if empleado_id:
        where.append("p.empleado_id = %s")
        params.append(int(empleado_id))
    if search:
        like = f"%{search}%"
        where.append(
            "(e.apellido LIKE %s OR e.nombre LIKE %s OR e.dni LIKE %s OR EXISTS ("
            "SELECT 1 FROM pedidos_mercaderia_items i "
            "WHERE i.pedido_id = p.id AND (i.codigo_articulo_snapshot LIKE %s OR i.descripcion_snapshot LIKE %s)"
            "))"
        )
        params.extend([like, like, like, like, like])
    if estado:
        where.append("p.estado = %s")
        params.append(estado)
    if periodo_year:
        where.append("p.periodo_year = %s")
        params.append(int(periodo_year))
    if periodo_month:
        where.append("p.periodo_month = %s")
        params.append(int(periodo_month))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def get_page(
    page: int,
    per_page: int,
    *,
    empleado_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )

        cursor.execute(
            f"""
            {_base_select()}
            {where_sql}
            ORDER BY p.periodo_year DESC, p.periodo_month DESC, p.created_at DESC, p.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM pedidos_mercaderia p
            JOIN empleados e ON e.id = p.empleado_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_summary(
    *,
    empleado_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN p.estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes,
                SUM(CASE WHEN p.estado = 'aprobado' THEN 1 ELSE 0 END) AS aprobados,
                SUM(CASE WHEN p.estado = 'rechazado' THEN 1 ELSE 0 END) AS rechazados,
                SUM(CASE WHEN p.estado = 'cancelado' THEN 1 ELSE 0 END) AS cancelados
            FROM pedidos_mercaderia p
            JOIN empleados e ON e.id = p.empleado_id
            {where_sql}
            """,
            tuple(params),
        )
        row = cursor.fetchone() or {}
        return {
            "total": int(row.get("total") or 0),
            "pendientes": int(row.get("pendientes") or 0),
            "aprobados": int(row.get("aprobados") or 0),
            "rechazados": int(row.get("rechazados") or 0),
            "cancelados": int(row.get("cancelados") or 0),
        }
    finally:
        cursor.close()
        db.close()


def get_export(
    *,
    empleado_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
    limit: int = 10000,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        cursor.execute(
            f"""
            SELECT
                p.id,
                p.periodo_year,
                p.periodo_month,
                p.fecha_pedido,
                p.estado,
                p.resuelto_at,
                p.motivo_rechazo,
                e.dni,
                e.nombre,
                e.apellido,
                emp.razon_social AS empresa_nombre,
                u.usuario AS resuelto_by_usuario,
                i.codigo_articulo_snapshot,
                i.descripcion_snapshot,
                i.cantidad_bultos,
                i.unidades_por_bulto_snapshot
            FROM pedidos_mercaderia p
            JOIN empleados e ON e.id = p.empleado_id
            JOIN empresas emp ON emp.id = p.empresa_id
            LEFT JOIN usuarios u ON u.id = p.resuelto_by_usuario_id
            JOIN pedidos_mercaderia_items i ON i.pedido_id = p.id
            {where_sql}
            ORDER BY p.periodo_year DESC, p.periodo_month DESC, p.id DESC, i.descripcion_snapshot
            LIMIT %s
            """,
            (*params, int(limit)),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def create(data: dict, items: list[dict]):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO pedidos_mercaderia
            (
                empresa_id,
                empleado_id,
                periodo_year,
                periodo_month,
                fecha_pedido,
                estado
            )
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("empresa_id"),
                data.get("empleado_id"),
                data.get("periodo_year"),
                data.get("periodo_month"),
                data.get("fecha_pedido"),
                data.get("estado") or "pendiente",
            ),
        )
        pedido_id = cursor.lastrowid
        _insert_items(cursor, pedido_id, items)
        db.commit()
        return pedido_id
    finally:
        cursor.close()
        db.close()


def replace_items(pedido_id: int, items: list[dict]) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM pedidos_mercaderia_items WHERE pedido_id = %s", (pedido_id,))
        _insert_items(cursor, pedido_id, items)
        db.commit()
    finally:
        cursor.close()
        db.close()


def _insert_items(cursor, pedido_id: int, items: list[dict]) -> None:
    if not items:
        return
    cursor.executemany(
        """
        INSERT INTO pedidos_mercaderia_items
        (
            pedido_id,
            articulo_id,
            cantidad_bultos,
            codigo_articulo_snapshot,
            descripcion_snapshot,
            unidades_por_bulto_snapshot
        )
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        [
            (
                pedido_id,
                item.get("articulo_id"),
                item.get("cantidad_bultos"),
                item.get("codigo_articulo_snapshot"),
                item.get("descripcion_snapshot"),
                item.get("unidades_por_bulto_snapshot"),
            )
            for item in items
        ],
    )


def update_estado(
    pedido_id: int,
    estado: str,
    *,
    resuelto_by_usuario_id: int | None = None,
    motivo_rechazo: str | None = None,
) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        resolved_by = int(resuelto_by_usuario_id) if resuelto_by_usuario_id else None
        resolved_at_sql = "NOW()" if estado in {"aprobado", "rechazado", "cancelado"} else "NULL"
        motivo = (motivo_rechazo or "").strip() or None
        cursor.execute(
            f"""
            UPDATE pedidos_mercaderia
            SET
                estado = %s,
                resuelto_by_usuario_id = %s,
                resuelto_at = {resolved_at_sql},
                motivo_rechazo = %s
            WHERE id = %s
            """,
            (estado, resolved_by, motivo if estado == "rechazado" else None, pedido_id),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()
