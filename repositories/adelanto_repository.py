from extensions import get_db


def _get_empresa_id_for_empleado(cursor, empleado_id: int | None):
    if not empleado_id:
        return None
    cursor.execute(
        """
        SELECT empresa_id
        FROM empleados
        WHERE id = %s
        LIMIT 1
        """,
        (empleado_id,),
    )
    row = cursor.fetchone()
    if isinstance(row, dict):
        return row.get("empresa_id")
    return row[0] if row else None


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _adelantos_resolution_support(cursor) -> tuple[bool, bool]:
    has_resolved_by = _column_exists(cursor, "adelantos", "resuelto_by_usuario_id")
    has_resolved_at = _column_exists(cursor, "adelantos", "resuelto_at")
    return has_resolved_by, has_resolved_at


def get_by_id(adelanto_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        has_resolved_by, has_resolved_at = _adelantos_resolution_support(cursor)
        extra_select = ["NULL AS resuelto_by_usuario"] if not has_resolved_by else ["u.usuario AS resuelto_by_usuario"]
        if not has_resolved_at:
            extra_select.append("NULL AS resuelto_at")
        join_sql = "LEFT JOIN usuarios u ON u.id = a.resuelto_by_usuario_id" if has_resolved_by else ""
        cursor.execute(
            f"""
            SELECT
                a.*,
                {", ".join(extra_select)}
            FROM adelantos a
            {join_sql}
            WHERE a.id = %s
            """,
            (adelanto_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_empleado_periodo(empleado_id: int, periodo_year: int, periodo_month: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM adelantos
            WHERE empleado_id = %s
              AND periodo_year = %s
              AND periodo_month = %s
            LIMIT 1
            """,
            (empleado_id, periodo_year, periodo_month),
        )
        return cursor.fetchone()
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
        has_resolved_by, has_resolved_at = _adelantos_resolution_support(cursor)
        offset = max(0, (int(page) - 1) * int(per_page))
        where = ["a.empleado_id = %s"]
        params = [int(empleado_id)]
        if estado:
            where.append("a.estado = %s")
            params.append(estado)
        where_sql = "WHERE " + " AND ".join(where)
        extra_select = ["NULL AS resuelto_by_usuario"] if not has_resolved_by else ["u.usuario AS resuelto_by_usuario"]
        if not has_resolved_at:
            extra_select.append("NULL AS resuelto_at")
        join_sql = "LEFT JOIN usuarios u ON u.id = a.resuelto_by_usuario_id" if has_resolved_by else ""

        cursor.execute(
            f"""
            SELECT
                a.*,
                {", ".join(extra_select)}
            FROM adelantos a
            {join_sql}
            {where_sql}
            ORDER BY a.periodo_year DESC, a.periodo_month DESC, a.created_at DESC, a.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM adelantos a
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
        where.append("a.empleado_id = %s")
        params.append(int(empleado_id))
    if search:
        like = f"%{search}%"
        where.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.dni LIKE %s)")
        params.extend([like, like, like])
    if estado:
        where.append("a.estado = %s")
        params.append(estado)
    if periodo_year:
        where.append("a.periodo_year = %s")
        params.append(int(periodo_year))
    if periodo_month:
        where.append("a.periodo_month = %s")
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
        has_resolved_by, has_resolved_at = _adelantos_resolution_support(cursor)
        offset = max(0, (int(page) - 1) * int(per_page))
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        extra_select = ["NULL AS resuelto_by_usuario"] if not has_resolved_by else ["u.usuario AS resuelto_by_usuario"]
        if not has_resolved_at:
            extra_select.append("NULL AS resuelto_at")
        join_sql = "LEFT JOIN usuarios u ON u.id = a.resuelto_by_usuario_id" if has_resolved_by else ""

        cursor.execute(
            f"""
            SELECT
                a.*,
                e.nombre,
                e.apellido,
                e.dni,
                emp.razon_social AS empresa_nombre,
                {", ".join(extra_select)}
            FROM adelantos a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            {join_sql}
            {where_sql}
            ORDER BY a.periodo_year DESC, a.periodo_month DESC, a.created_at DESC, a.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM adelantos a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)
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
                SUM(CASE WHEN a.estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes,
                SUM(CASE WHEN a.estado = 'aprobado' THEN 1 ELSE 0 END) AS aprobados,
                SUM(CASE WHEN a.estado = 'rechazado' THEN 1 ELSE 0 END) AS rechazados,
                SUM(CASE WHEN a.estado = 'cancelado' THEN 1 ELSE 0 END) AS cancelados
            FROM adelantos a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
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
        has_resolved_by, has_resolved_at = _adelantos_resolution_support(cursor)
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        extra_select = ["NULL AS resuelto_by_usuario"] if not has_resolved_by else ["u.usuario AS resuelto_by_usuario"]
        if not has_resolved_at:
            extra_select.append("NULL AS resuelto_at")
        join_sql = "LEFT JOIN usuarios u ON u.id = a.resuelto_by_usuario_id" if has_resolved_by else ""
        cursor.execute(
            f"""
            SELECT
                a.*,
                e.nombre,
                e.apellido,
                e.dni,
                emp.razon_social AS empresa_nombre,
                {", ".join(extra_select)}
            FROM adelantos a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            {join_sql}
            {where_sql}
            ORDER BY a.periodo_year DESC, a.periodo_month DESC, a.created_at DESC, a.id DESC
            LIMIT %s
            """,
            (*params, int(limit)),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def update_estado(adelanto_id: int, estado: str, *, resuelto_by_usuario_id: int | None = None) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        has_resolved_by, has_resolved_at = _adelantos_resolution_support(cursor)
        resolved_by = int(resuelto_by_usuario_id) if resuelto_by_usuario_id else None
        set_clauses = ["estado = %s"]
        params = [estado]
        if has_resolved_by:
            set_clauses.append("resuelto_by_usuario_id = %s")
            params.append(resolved_by)
        if has_resolved_at:
            resolved_at_sql = "NOW()" if estado in {"aprobado", "rechazado", "cancelado"} else "NULL"
            set_clauses.append(f"resuelto_at = {resolved_at_sql}")
        cursor.execute(
            f"""
            UPDATE adelantos
            SET {", ".join(set_clauses)}
            WHERE id = %s
            """,
            (*params, adelanto_id),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        empleado_id = data.get("empleado_id")
        empresa_id = data.get("empresa_id") or _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")

        cursor.execute(
            """
            INSERT INTO adelantos
            (
                empresa_id,
                empleado_id,
                periodo_year,
                periodo_month,
                fecha_solicitud,
                estado
            )
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                empresa_id,
                empleado_id,
                data.get("periodo_year"),
                data.get("periodo_month"),
                data.get("fecha_solicitud"),
                data.get("estado") or "pendiente",
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()
