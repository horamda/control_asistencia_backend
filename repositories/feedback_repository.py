from extensions import get_db
from utils.search import build_tokenized_like_clause


def _base_select_sql() -> str:
    estado_actual = """
        CASE
            WHEN f.estado = 'resuelto' THEN 'resuelto'
            WHEN f.estado IN ('pendiente', 'en_proceso') AND CURDATE() > f.fecha_vencimiento THEN 'vencido'
            ELSE f.estado
        END
    """
    return f"""
        SELECT
            f.id,
            f.empresa_id,
            f.empleado_id,
            f.jefe_directo_id,
            f.cliente_id,
            f.motivo_id,
            f.descripcion,
            f.estado,
            {estado_actual} AS estado_actual,
            f.fecha_vencimiento,
            f.cliente_codigo_snapshot,
            f.cliente_razon_social_snapshot,
            f.cliente_nombre_fantasia_snapshot,
            f.cliente_tipo_snapshot,
            f.motivo_nombre_snapshot,
            f.jefe_directo_nombre_snapshot,
            f.created_at,
            f.updated_at,
            f.resuelto_at,
            f.resuelto_por_empleado_id,
            f.resolucion_descripcion,
            COALESCE(f.resuelto_en_sla, 0) AS resuelto_en_sla,
            DATEDIFF(f.fecha_vencimiento, CURDATE()) AS dias_restantes,
            ee.legajo AS empleado_legajo,
            ee.dni AS empleado_dni,
            CONCAT(ee.apellido, ' ', ee.nombre) AS empleado_nombre,
            ee.sector_id AS empleado_sector_id,
            ee.activo AS empleado_activo,
            sec.nombre AS empleado_sector_nombre,
            jd.legajo AS jefe_directo_legajo,
            jd.dni AS jefe_directo_dni,
            COALESCE(
                CONCAT(jd.apellido, ' ', jd.nombre),
                f.jefe_directo_nombre_snapshot
            ) AS jefe_directo_nombre,
            COALESCE(c.codigo_externo, f.cliente_codigo_snapshot) AS cliente_codigo,
            COALESCE(c.razon_social, f.cliente_razon_social_snapshot) AS cliente_razon_social,
            COALESCE(c.nombre_fantasia, f.cliente_nombre_fantasia_snapshot) AS cliente_nombre_fantasia,
            COALESCE(c.tipo_descripcion, f.cliente_tipo_snapshot) AS cliente_tipo,
            COALESCE(m.nombre, f.motivo_nombre_snapshot) AS motivo_nombre,
            res.legajo AS resuelto_por_legajo,
            COALESCE(CONCAT(res.apellido, ' ', res.nombre), '') AS resuelto_por_nombre
        FROM feedbacks f
        JOIN empleados ee ON ee.id = f.empleado_id
        LEFT JOIN sectores sec ON sec.id = ee.sector_id
        LEFT JOIN empleados jd ON jd.id = f.jefe_directo_id
        LEFT JOIN feedback_clientes c ON c.id = f.cliente_id
        LEFT JOIN feedback_motivos m ON m.id = f.motivo_id
        LEFT JOIN empleados res ON res.id = f.resuelto_por_empleado_id
    """


def _build_where(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    jefe_directo_id: int | None = None,
    estado: str | None = None,
    search: str | None = None,
    cliente_id: int | None = None,
    motivo_id: int | None = None,
    sector_id: int | None = None,
    empleado_activo: int | None = None,
):
    where = []
    params: list = []

    if empresa_id:
        where.append("fb.empresa_id = %s")
        params.append(int(empresa_id))
    if empleado_id:
        where.append("fb.empleado_id = %s")
        params.append(int(empleado_id))
    if jefe_directo_id:
        where.append("fb.jefe_directo_id = %s")
        params.append(int(jefe_directo_id))
    if cliente_id:
        where.append("fb.cliente_id = %s")
        params.append(int(cliente_id))
    if motivo_id:
        where.append("fb.motivo_id = %s")
        params.append(int(motivo_id))
    if sector_id:
        where.append("fb.empleado_sector_id = %s")
        params.append(int(sector_id))
    if empleado_activo in (0, 1):
        where.append("fb.empleado_activo = %s")
        params.append(int(empleado_activo))
    if estado:
        estado_norm = str(estado).strip().lower()
        if estado_norm in {"pendiente", "en_proceso", "resuelto", "vencido"}:
            where.append("fb.estado_actual = %s")
            params.append(estado_norm)
    if search:
        clause, clause_params = build_tokenized_like_clause(
            [
                "CAST(fb.id AS CHAR)",
                "fb.estado",
                "fb.estado_actual",
                "fb.cliente_razon_social",
                "fb.cliente_nombre_fantasia",
                "fb.cliente_codigo",
                "fb.cliente_razon_social_snapshot",
                "fb.cliente_nombre_fantasia_snapshot",
                "fb.cliente_codigo_snapshot",
                "fb.motivo_nombre",
                "fb.motivo_nombre_snapshot",
                "fb.descripcion",
                "fb.resolucion_descripcion",
                "fb.empleado_nombre",
                "fb.empleado_legajo",
                "fb.empleado_dni",
                "fb.jefe_directo_nombre",
                "fb.jefe_directo_legajo",
                "fb.jefe_directo_dni",
                "fb.resuelto_por_nombre",
                "fb.resuelto_por_legajo",
            ],
            search,
            max_terms=5,
        )
        if clause:
            where.append(clause)
            params.extend(clause_params)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def _fetch_page(page: int, per_page: int, where_sql: str, params: list):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        base = f"SELECT * FROM ({_base_select_sql()}) fb"
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM ({_base_select_sql()}) fb
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)

        cursor.execute(
            f"""
            {base}
            {where_sql}
            ORDER BY fb.created_at DESC, fb.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall() or []
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(feedback_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT *
            FROM ({_base_select_sql()}) fb
            WHERE fb.id = %s
            LIMIT 1
            """,
            (feedback_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_page(
    page: int,
    per_page: int,
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    jefe_directo_id: int | None = None,
    estado: str | None = None,
    search: str | None = None,
    cliente_id: int | None = None,
    motivo_id: int | None = None,
    sector_id: int | None = None,
    empleado_activo: int | None = None,
):
    where_sql, params = _build_where(
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        jefe_directo_id=jefe_directo_id,
        estado=estado,
        search=search,
        cliente_id=cliente_id,
        motivo_id=motivo_id,
        sector_id=sector_id,
        empleado_activo=empleado_activo,
    )
    return _fetch_page(page, per_page, where_sql, params)


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO feedbacks
            (
                empresa_id,
                empleado_id,
                jefe_directo_id,
                cliente_id,
                motivo_id,
                descripcion,
                estado,
                fecha_vencimiento,
                cliente_codigo_snapshot,
                cliente_razon_social_snapshot,
                cliente_nombre_fantasia_snapshot,
                cliente_tipo_snapshot,
                motivo_nombre_snapshot,
                jefe_directo_nombre_snapshot
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("empresa_id"),
                data.get("empleado_id"),
                data.get("jefe_directo_id"),
                data.get("cliente_id"),
                data.get("motivo_id"),
                data.get("descripcion"),
                data.get("estado") or "pendiente",
                data.get("fecha_vencimiento"),
                data.get("cliente_codigo_snapshot"),
                data.get("cliente_razon_social_snapshot"),
                data.get("cliente_nombre_fantasia_snapshot"),
                data.get("cliente_tipo_snapshot"),
                data.get("motivo_nombre_snapshot"),
                data.get("jefe_directo_nombre_snapshot"),
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_estado(
    feedback_id: int,
    estado: str,
    *,
    resuelto_at=None,
    resuelto_por_empleado_id: int | None = None,
    resolucion_descripcion: str | None = None,
    resuelto_en_sla: bool | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedbacks
            SET estado = %s,
                resuelto_at = %s,
                resuelto_por_empleado_id = %s,
                resolucion_descripcion = %s,
                resuelto_en_sla = %s
            WHERE id = %s
            """,
            (
                estado,
                resuelto_at,
                resuelto_por_empleado_id,
                resolucion_descripcion,
                1 if resuelto_en_sla else (0 if resuelto_en_sla is not None else None),
                feedback_id,
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def count_feedbacks(*, empresa_id: int | None = None, sector_id: int | None = None, empleado_activo: int | None = None) -> dict:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if empresa_id:
            where.append("f.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(int(sector_id))
        if empleado_activo in (0, 1):
            where.append("e.activo = %s")
            params.append(int(empleado_activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN f.estado = 'resuelto' THEN 1 ELSE 0 END) AS resueltos,
                SUM(CASE WHEN f.estado = 'pendiente' AND CURDATE() <= f.fecha_vencimiento THEN 1 ELSE 0 END) AS pendientes,
                SUM(CASE WHEN f.estado = 'en_proceso' AND CURDATE() <= f.fecha_vencimiento THEN 1 ELSE 0 END) AS en_proceso,
                SUM(CASE WHEN f.estado IN ('pendiente', 'en_proceso') AND CURDATE() > f.fecha_vencimiento THEN 1 ELSE 0 END) AS vencidos,
                SUM(CASE WHEN f.estado = 'resuelto' AND COALESCE(f.resuelto_en_sla, 0) = 1 THEN 1 ELSE 0 END) AS resueltos_en_sla,
                SUM(CASE WHEN f.estado = 'resuelto' AND COALESCE(f.resuelto_en_sla, 0) = 0 THEN 1 ELSE 0 END) AS resueltos_fuera_sla,
                COUNT(DISTINCT f.motivo_id) AS motivos_distintos,
                COUNT(DISTINCT f.cliente_id) AS clientes_distintos,
                COUNT(DISTINCT f.empleado_id) AS empleados_con_carga
            FROM feedbacks f
            JOIN empleados e ON e.id = f.empleado_id
            {where_sql}
            """,
            tuple(params),
        )
        row = cursor.fetchone() or {}
        return {
            "total": int(row.get("total") or 0),
            "resueltos": int(row.get("resueltos") or 0),
            "pendientes": int(row.get("pendientes") or 0),
            "en_proceso": int(row.get("en_proceso") or 0),
            "vencidos": int(row.get("vencidos") or 0),
            "resueltos_en_sla": int(row.get("resueltos_en_sla") or 0),
            "resueltos_fuera_sla": int(row.get("resueltos_fuera_sla") or 0),
            "motivos_distintos": int(row.get("motivos_distintos") or 0),
            "clientes_distintos": int(row.get("clientes_distintos") or 0),
            "empleados_con_carga": int(row.get("empleados_con_carga") or 0),
        }
    finally:
        cursor.close()
        db.close()


def get_top_motivos(*, empresa_id: int | None = None, sector_id: int | None = None, empleado_activo: int | None = None, limit: int = 5):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if empresa_id:
            where.append("f.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(int(sector_id))
        if empleado_activo in (0, 1):
            where.append("e.activo = %s")
            params.append(int(empleado_activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(
            f"""
            SELECT
                f.motivo_id,
                COALESCE(m.nombre, f.motivo_nombre_snapshot) AS motivo_nombre,
                COUNT(*) AS total,
                SUM(CASE WHEN f.estado = 'resuelto' THEN 1 ELSE 0 END) AS resueltos
            FROM feedbacks f
            JOIN empleados e ON e.id = f.empleado_id
            LEFT JOIN feedback_motivos m ON m.id = f.motivo_id
            {where_sql}
            GROUP BY f.motivo_id, motivo_nombre
            ORDER BY total DESC, motivo_nombre ASC
            LIMIT %s
            """,
            (*params, int(limit)),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_ranking_carga(*, empresa_id: int | None = None, sector_id: int | None = None, empleado_activo: int | None = None, limit: int | None = 10):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(int(sector_id))
        if empleado_activo in (0, 1):
            where.append("e.activo = %s")
            params.append(int(empleado_activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        join_filter = ""
        join_params = []
        if empresa_id:
            join_filter = "AND f.empresa_id = %s"
            join_params.append(int(empresa_id))

        cursor.execute(
            f"""
            SELECT
                e.id AS empleado_id,
                e.legajo,
                e.apellido,
                e.nombre,
                e.empresa_id,
                COALESCE(COUNT(f.id), 0) AS total
            FROM empleados e
            LEFT JOIN feedbacks f
              ON f.empleado_id = e.id
             {join_filter}
            {where_sql}
            GROUP BY e.id, e.legajo, e.apellido, e.nombre, e.empresa_id
            HAVING total > 0
            ORDER BY total DESC, e.apellido ASC, e.nombre ASC, e.id ASC
            """,
            tuple(join_params + params),
        )
        rows = cursor.fetchall() or []
        if limit:
            rows = rows[: int(limit)]
        return rows
    finally:
        cursor.close()
        db.close()


def count_active_empleados(*, empresa_id: int | None = None, sector_id: int | None = None, empleado_activo: int | None = None) -> int:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if empresa_id:
            where.append("empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("sector_id = %s")
            params.append(int(sector_id))
        if empleado_activo in (0, 1):
            where.append("activo = %s")
            params.append(int(empleado_activo))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM empleados
            {where_sql}
            """,
            tuple(params),
        )
        return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        cursor.close()
        db.close()
