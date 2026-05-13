import datetime

from extensions import get_db


MONTH_NAMES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def _normalize_codigo(value: str | None) -> str:
    return str(value or "").strip().upper()


def _periodo_date(value) -> str:
    if isinstance(value, datetime.datetime):
        return value.date().replace(day=1).isoformat()
    if isinstance(value, datetime.date):
        return value.replace(day=1).isoformat()
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Periodo requerido.")
    if len(raw) == 7:
        raw = f"{raw}-01"
    try:
        parsed = datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Periodo invalido. Use YYYY-MM o YYYY-MM-DD.") from exc
    return parsed.replace(day=1).isoformat()


def _periodo_parts(value) -> tuple[int, int]:
    periodo = _periodo_date(value)
    parsed = datetime.date.fromisoformat(periodo)
    return parsed.year, parsed.month


def _base_concurso_select():
    return """
        SELECT
            c.*,
            emp.razon_social AS empresa_nombre,
            s.nombre AS sector_nombre
        FROM premios_concursos c
        JOIN empresas emp ON emp.id = c.empresa_id
        LEFT JOIN sectores s ON s.id = c.sector_id
    """


def _build_concurso_filters(
    *,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    activo: int | None = None,
    alcance: str | None = None,
):
    where = []
    params = []
    if empresa_id:
        where.append("c.empresa_id = %s")
        params.append(int(empresa_id))
    if sector_id:
        where.append("c.sector_id = %s")
        params.append(int(sector_id))
    if search:
        like = f"%{search}%"
        where.append("(c.codigo LIKE %s OR c.nombre LIKE %s OR c.descripcion LIKE %s)")
        params.extend([like, like, like])
    if activo in (0, 1):
        where.append("c.activo = %s")
        params.append(int(activo))
    if alcance in {"sector", "global"}:
        where.append("c.alcance = %s")
        params.append(alcance)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def get_concursos_page(
    page: int,
    per_page: int,
    *,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    activo: int | None = None,
    alcance: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where_sql, params = _build_concurso_filters(
            empresa_id=empresa_id,
            sector_id=sector_id,
            search=search,
            activo=activo,
            alcance=alcance,
        )
        cursor.execute(
            f"""
            {_base_concurso_select()}
            {where_sql}
            ORDER BY emp.razon_social, c.alcance, s.nombre, c.nombre
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM premios_concursos c
            LEFT JOIN sectores s ON s.id = c.sector_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_concursos_for_empresa(empresa_id: int, *, activo: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["c.empresa_id = %s"]
        params = [int(empresa_id)]
        if activo in (0, 1):
            where.append("c.activo = %s")
            params.append(int(activo))
        cursor.execute(
            f"""
            {_base_concurso_select()}
            WHERE {" AND ".join(where)}
            ORDER BY
              CASE WHEN c.alcance = 'global' THEN 0 ELSE 1 END,
              s.nombre,
              c.nombre
            """,
            tuple(params),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_concurso_by_id(concurso_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_base_concurso_select()}
            WHERE c.id = %s
            LIMIT 1
            """,
            (int(concurso_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_concurso_by_codigo(empresa_id: int, codigo: str, *, activo: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["c.empresa_id = %s", "c.codigo = %s"]
        params = [int(empresa_id), _normalize_codigo(codigo)]
        if activo in (0, 1):
            where.append("c.activo = %s")
            params.append(int(activo))
        cursor.execute(
            f"""
            {_base_concurso_select()}
            WHERE {" AND ".join(where)}
            LIMIT 1
            """,
            tuple(params),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create_concurso(data: dict) -> int:
    db = get_db()
    cursor = db.cursor()
    try:
        alcance = str(data.get("alcance") or "sector").strip().lower()
        sector_id = data.get("sector_id") if alcance == "sector" else None
        cursor.execute(
            """
            INSERT INTO premios_concursos
              (empresa_id, sector_id, codigo, nombre, descripcion, alcance, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.get("empresa_id"),
                sector_id,
                _normalize_codigo(data.get("codigo")),
                data.get("nombre"),
                data.get("descripcion") or None,
                alcance,
                1 if data.get("activo", True) else 0,
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_concurso(concurso_id: int, data: dict) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        alcance = str(data.get("alcance") or "sector").strip().lower()
        sector_id = data.get("sector_id") if alcance == "sector" else None
        cursor.execute(
            """
            UPDATE premios_concursos
            SET
              empresa_id = %s,
              sector_id = %s,
              codigo = %s,
              nombre = %s,
              descripcion = %s,
              alcance = %s,
              activo = %s
            WHERE id = %s
            """,
            (
                data.get("empresa_id"),
                sector_id,
                _normalize_codigo(data.get("codigo")),
                data.get("nombre"),
                data.get("descripcion") or None,
                alcance,
                1 if data.get("activo", True) else 0,
                int(concurso_id),
            ),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def set_concurso_activo(concurso_id: int, activo: int) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE premios_concursos SET activo = %s WHERE id = %s",
            (1 if activo else 0, int(concurso_id)),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def _base_resultado_select():
    return """
        SELECT
            r.*,
            DATE_FORMAT(r.periodo, '%Y-%m') AS periodo_label,
            YEAR(r.periodo) AS periodo_year,
            MONTH(r.periodo) AS periodo_month,
            e.nombre,
            e.apellido,
            e.dni,
            e.legajo,
            emp.razon_social AS empresa_nombre,
            c.codigo AS concurso_codigo,
            c.nombre AS concurso_nombre,
            c.alcance AS concurso_alcance,
            c.sector_id AS concurso_sector_id,
            sc.nombre AS concurso_sector_nombre,
            sr.nombre AS sector_nombre,
            u_created.usuario AS created_by_usuario,
            u_updated.usuario AS updated_by_usuario
        FROM premios_resultados r
        JOIN empleados e ON e.id = r.empleado_id
        JOIN empresas emp ON emp.id = r.empresa_id
        JOIN premios_concursos c ON c.id = r.concurso_id
        LEFT JOIN sectores sc ON sc.id = c.sector_id
        LEFT JOIN sectores sr ON sr.id = r.sector_id
        LEFT JOIN usuarios u_created ON u_created.id = r.created_by_usuario_id
        LEFT JOIN usuarios u_updated ON u_updated.id = r.updated_by_usuario_id
    """


def _build_resultado_filters(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    concurso_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
):
    where = []
    params = []
    if empresa_id:
        where.append("r.empresa_id = %s")
        params.append(int(empresa_id))
    if empleado_id:
        where.append("r.empleado_id = %s")
        params.append(int(empleado_id))
    if concurso_id:
        where.append("r.concurso_id = %s")
        params.append(int(concurso_id))
    if sector_id:
        where.append("r.sector_id = %s")
        params.append(int(sector_id))
    if search:
        like = f"%{search}%"
        where.append(
            "("
            "e.apellido LIKE %s OR e.nombre LIKE %s OR e.dni LIKE %s OR e.legajo LIKE %s "
            "OR c.codigo LIKE %s OR c.nombre LIKE %s"
            ")"
        )
        params.extend([like, like, like, like, like, like])
    if periodo_year:
        where.append("YEAR(r.periodo) = %s")
        params.append(int(periodo_year))
    if periodo_month:
        where.append("MONTH(r.periodo) = %s")
        params.append(int(periodo_month))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def get_resultados_page(
    page: int,
    per_page: int,
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    concurso_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where_sql, params = _build_resultado_filters(
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            concurso_id=concurso_id,
            sector_id=sector_id,
            search=search,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        cursor.execute(
            f"""
            {_base_resultado_select()}
            {where_sql}
            ORDER BY r.periodo DESC, c.nombre, r.ranking, e.apellido, e.nombre
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM premios_resultados r
            JOIN empleados e ON e.id = r.empleado_id
            JOIN premios_concursos c ON c.id = r.concurso_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_resultados_summary(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    concurso_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_resultado_filters(
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            concurso_id=concurso_id,
            sector_id=sector_id,
            search=search,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN r.ranking = 1 THEN 1 ELSE 0 END) AS primeros,
                SUM(CASE WHEN r.ranking BETWEEN 1 AND 3 THEN 1 ELSE 0 END) AS podios,
                COUNT(DISTINCT r.empleado_id) AS empleados,
                COUNT(DISTINCT r.concurso_id) AS concursos
            FROM premios_resultados r
            JOIN empleados e ON e.id = r.empleado_id
            JOIN premios_concursos c ON c.id = r.concurso_id
            {where_sql}
            """,
            tuple(params),
        )
        row = cursor.fetchone() or {}
        return {
            "total": int(row.get("total") or 0),
            "primeros": int(row.get("primeros") or 0),
            "podios": int(row.get("podios") or 0),
            "empleados": int(row.get("empleados") or 0),
            "concursos": int(row.get("concursos") or 0),
        }
    finally:
        cursor.close()
        db.close()


def get_resultados_export(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    concurso_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    periodo_year: int | None = None,
    periodo_month: int | None = None,
    limit: int = 10000,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_resultado_filters(
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            concurso_id=concurso_id,
            sector_id=sector_id,
            search=search,
            periodo_year=periodo_year,
            periodo_month=periodo_month,
        )
        cursor.execute(
            f"""
            {_base_resultado_select()}
            {where_sql}
            ORDER BY r.periodo DESC, c.nombre, r.ranking, e.apellido, e.nombre
            LIMIT %s
            """,
            (*params, int(limit)),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_resultado_by_id(resultado_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_base_resultado_select()}
            WHERE r.id = %s
            LIMIT 1
            """,
            (int(resultado_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_empleados_lookup_by_empresa(empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                e.id,
                e.empresa_id,
                e.legajo,
                e.nombre,
                e.apellido,
                e.dni,
                e.sector_id,
                s.nombre AS sector_nombre
            FROM empleados e
            LEFT JOIN sectores s ON s.id = e.sector_id
            WHERE e.empresa_id = %s
            """,
            (int(empresa_id),),
        )
        return {
            str(row.get("legajo") or "").strip(): row
            for row in cursor.fetchall()
            if str(row.get("legajo") or "").strip()
        }
    finally:
        cursor.close()
        db.close()


def _fetch_empleado(cursor, empresa_id: int, empleado_id: int):
    cursor.execute(
        """
        SELECT
            e.id,
            e.empresa_id,
            e.legajo,
            e.nombre,
            e.apellido,
            e.dni,
            e.sector_id,
            s.nombre AS sector_nombre
        FROM empleados e
        LEFT JOIN sectores s ON s.id = e.sector_id
        WHERE e.empresa_id = %s AND e.id = %s
        LIMIT 1
        """,
        (int(empresa_id), int(empleado_id)),
    )
    return cursor.fetchone()


def _fetch_concurso(cursor, empresa_id: int, concurso_id: int):
    cursor.execute(
        """
        SELECT
            c.*,
            s.nombre AS sector_nombre
        FROM premios_concursos c
        LEFT JOIN sectores s ON s.id = c.sector_id
        WHERE c.empresa_id = %s AND c.id = %s
        LIMIT 1
        """,
        (int(empresa_id), int(concurso_id)),
    )
    return cursor.fetchone()


def _validate_resultado_data(empleado: dict, concurso: dict) -> None:
    if not empleado:
        raise ValueError("Empleado no encontrado para la empresa seleccionada.")
    if not concurso:
        raise ValueError("Concurso no encontrado para la empresa seleccionada.")
    alcance = str(concurso.get("alcance") or "").lower()
    if alcance == "sector" and int(empleado.get("sector_id") or 0) != int(concurso.get("sector_id") or 0):
        raise ValueError("El empleado no pertenece al sector configurado para este concurso.")


def _prepare_resultado(
    *,
    empresa_id: int,
    empleado: dict,
    concurso: dict,
    periodo,
    ranking: int,
    observaciones: str | None = None,
    actor_id: int | None = None,
) -> dict:
    _validate_resultado_data(empleado, concurso)
    ranking_int = int(ranking)
    if ranking_int < 1:
        raise ValueError("Ranking debe ser mayor o igual a 1.")
    apellido = str(empleado.get("apellido") or "").strip()
    nombre = str(empleado.get("nombre") or "").strip()
    empleado_nombre = f"{apellido} {nombre}".strip()
    return {
        "empresa_id": int(empresa_id),
        "empleado_id": int(empleado["id"]),
        "concurso_id": int(concurso["id"]),
        "sector_id": empleado.get("sector_id"),
        "periodo": _periodo_date(periodo),
        "ranking": ranking_int,
        "legajo_snapshot": str(empleado.get("legajo") or "").strip(),
        "empleado_nombre_snapshot": empleado_nombre,
        "concurso_codigo_snapshot": _normalize_codigo(concurso.get("codigo")),
        "concurso_nombre_snapshot": str(concurso.get("nombre") or "").strip(),
        "observaciones": (observaciones or "").strip() or None,
        "actor_id": int(actor_id) if actor_id else None,
    }


def _existing_resultado_id(cursor, empleado_id: int, concurso_id: int, periodo: str, *, exclude_id: int | None = None):
    params = [int(empleado_id), int(concurso_id), periodo]
    extra = ""
    if exclude_id:
        extra = "AND id <> %s"
        params.append(int(exclude_id))
    cursor.execute(
        f"""
        SELECT id
        FROM premios_resultados
        WHERE empleado_id = %s
          AND concurso_id = %s
          AND periodo = %s
          {extra}
        LIMIT 1
        """,
        tuple(params),
    )
    row = cursor.fetchone()
    return int(row["id"]) if row else None


def _ranking_conflict_id(
    cursor,
    concurso_id: int,
    periodo: str,
    ranking: int,
    *,
    exclude_id: int | None = None,
):
    params = [int(concurso_id), periodo, int(ranking)]
    extra = ""
    if exclude_id:
        extra = "AND id <> %s"
        params.append(int(exclude_id))
    cursor.execute(
        f"""
        SELECT id
        FROM premios_resultados
        WHERE concurso_id = %s
          AND periodo = %s
          AND ranking = %s
          {extra}
        LIMIT 1
        """,
        tuple(params),
    )
    row = cursor.fetchone()
    return int(row["id"]) if row else None


def _save_prepared_resultado(cursor, prepared: dict, *, resultado_id: int | None = None):
    target_id = int(resultado_id) if resultado_id else None
    if target_id:
        cursor.execute("SELECT id FROM premios_resultados WHERE id = %s LIMIT 1", (target_id,))
        if not cursor.fetchone():
            raise ValueError("Resultado no encontrado.")
        duplicate_id = _existing_resultado_id(
            cursor,
            prepared["empleado_id"],
            prepared["concurso_id"],
            prepared["periodo"],
            exclude_id=target_id,
        )
        if duplicate_id:
            raise ValueError("Ya existe un resultado para ese empleado, concurso y periodo.")
    else:
        target_id = _existing_resultado_id(
            cursor,
            prepared["empleado_id"],
            prepared["concurso_id"],
            prepared["periodo"],
        )

    ranking_conflict = _ranking_conflict_id(
        cursor,
        prepared["concurso_id"],
        prepared["periodo"],
        prepared["ranking"],
        exclude_id=target_id,
    )
    if ranking_conflict:
        raise ValueError("Ya existe otro empleado con ese ranking para el concurso y periodo.")

    if target_id:
        cursor.execute(
            """
            UPDATE premios_resultados
            SET
              empresa_id = %s,
              empleado_id = %s,
              concurso_id = %s,
              sector_id = %s,
              periodo = %s,
              ranking = %s,
              legajo_snapshot = %s,
              empleado_nombre_snapshot = %s,
              concurso_codigo_snapshot = %s,
              concurso_nombre_snapshot = %s,
              observaciones = %s,
              updated_by_usuario_id = %s
            WHERE id = %s
            """,
            (
                prepared["empresa_id"],
                prepared["empleado_id"],
                prepared["concurso_id"],
                prepared["sector_id"],
                prepared["periodo"],
                prepared["ranking"],
                prepared["legajo_snapshot"],
                prepared["empleado_nombre_snapshot"],
                prepared["concurso_codigo_snapshot"],
                prepared["concurso_nombre_snapshot"],
                prepared["observaciones"],
                prepared["actor_id"],
                target_id,
            ),
        )
        return target_id, False

    cursor.execute(
        """
        INSERT INTO premios_resultados
        (
            empresa_id,
            empleado_id,
            concurso_id,
            sector_id,
            periodo,
            ranking,
            legajo_snapshot,
            empleado_nombre_snapshot,
            concurso_codigo_snapshot,
            concurso_nombre_snapshot,
            observaciones,
            created_by_usuario_id,
            updated_by_usuario_id
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            prepared["empresa_id"],
            prepared["empleado_id"],
            prepared["concurso_id"],
            prepared["sector_id"],
            prepared["periodo"],
            prepared["ranking"],
            prepared["legajo_snapshot"],
            prepared["empleado_nombre_snapshot"],
            prepared["concurso_codigo_snapshot"],
            prepared["concurso_nombre_snapshot"],
            prepared["observaciones"],
            prepared["actor_id"],
            prepared["actor_id"],
        ),
    )
    return cursor.lastrowid, True


def save_resultado(data: dict, *, resultado_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        empresa_id = int(data.get("empresa_id"))
        empleado = _fetch_empleado(cursor, empresa_id, int(data.get("empleado_id")))
        concurso = _fetch_concurso(cursor, empresa_id, int(data.get("concurso_id")))
        prepared = _prepare_resultado(
            empresa_id=empresa_id,
            empleado=empleado,
            concurso=concurso,
            periodo=data.get("periodo"),
            ranking=int(data.get("ranking")),
            observaciones=data.get("observaciones"),
            actor_id=data.get("actor_id"),
        )
        saved_id, created = _save_prepared_resultado(cursor, prepared, resultado_id=resultado_id)
        db.commit()
        return saved_id, created
    finally:
        cursor.close()
        db.close()


def save_prepared_resultado(prepared: dict, *, resultado_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        saved_id, created = _save_prepared_resultado(cursor, prepared, resultado_id=resultado_id)
        db.commit()
        return saved_id, created
    finally:
        cursor.close()
        db.close()


def build_prepared_resultado(
    *,
    empresa_id: int,
    empleado: dict,
    concurso: dict,
    periodo,
    ranking: int,
    observaciones: str | None = None,
    actor_id: int | None = None,
):
    return _prepare_resultado(
        empresa_id=empresa_id,
        empleado=empleado,
        concurso=concurso,
        periodo=periodo,
        ranking=ranking,
        observaciones=observaciones,
        actor_id=actor_id,
    )


def delete_resultado(resultado_id: int) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM premios_resultados WHERE id = %s", (int(resultado_id),))
        db.commit()
    finally:
        cursor.close()
        db.close()


def get_resultados_empleado_anio(empleado_id: int, anio: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT e.sector_id, s.nombre AS sector_nombre
            FROM empleados e
            LEFT JOIN sectores s ON s.id = e.sector_id
            WHERE e.id = %s
            LIMIT 1
            """,
            (int(empleado_id),),
        )
        empleado = cursor.fetchone() or {}

        cursor.execute(
            """
            SELECT
                r.id,
                r.periodo,
                DATE_FORMAT(r.periodo, '%Y-%m') AS periodo_label,
                YEAR(r.periodo) AS periodo_year,
                MONTH(r.periodo) AS periodo_month,
                r.ranking,
                r.observaciones,
                c.id AS concurso_id,
                c.codigo AS concurso_codigo,
                c.nombre AS concurso_nombre,
                c.descripcion AS concurso_descripcion,
                c.alcance AS concurso_alcance,
                c.sector_id AS concurso_sector_id,
                sc.nombre AS concurso_sector_nombre,
                sr.id AS empleado_sector_id,
                sr.nombre AS empleado_sector_nombre
            FROM premios_resultados r
            JOIN premios_concursos c ON c.id = r.concurso_id
            LEFT JOIN sectores sc ON sc.id = c.sector_id
            LEFT JOIN sectores sr ON sr.id = r.sector_id
            WHERE r.empleado_id = %s
              AND YEAR(r.periodo) = %s
            ORDER BY r.periodo ASC, r.ranking ASC, c.nombre ASC
            """,
            (int(empleado_id), int(anio)),
        )
        rows = cursor.fetchall()
        return {
            "sector_id": empleado.get("sector_id"),
            "sector_nombre": empleado.get("sector_nombre"),
            "premios": rows,
        }
    finally:
        cursor.close()
        db.close()
