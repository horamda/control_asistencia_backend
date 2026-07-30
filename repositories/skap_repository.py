from __future__ import annotations

from extensions import get_db


def _scope_filters(
    *,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    sucursal_id: int | None = None,
):
    where = []
    params: list = []
    if empresa_id:
        where.append("ev.empresa_id = %s")
        params.append(int(empresa_id))
    if sector_id:
        where.append("ev.sector_id = %s")
        params.append(int(sector_id))
    if sucursal_id:
        where.append("ev.empleado_sucursal_id = %s")
        params.append(int(sucursal_id))
    return where, params


def _evaluation_select() -> str:
    return """
        SELECT
            ev.id,
            ev.empresa_id,
            ev.empleado_id,
            ev.sector_id,
            ev.puesto_id,
            ev.anio,
            ev.evaluador_empleado_id,
            ev.evaluador_usuario_id,
            ev.fecha_evaluacion,
            ev.hora_evaluacion,
            ev.promedio_skills,
            ev.promedio_knowledge,
            ev.promedio_attitude,
            ev.promedio_performance,
            ev.promedio_general,
            ev.nivel,
            ev.observaciones_generales,
            ev.pdp_generado_at,
            ev.created_at,
            ev.updated_at,
            emp.activo AS empleado_activo,
            emp.legajo AS empleado_legajo,
            emp.dni AS empleado_dni,
            emp.apellido AS empleado_apellido,
            emp.nombre AS empleado_nombre,
            emp.sucursal_id AS empleado_sucursal_id,
            sec.nombre AS sector_nombre,
            suc.nombre AS sucursal_nombre,
            p.nombre AS puesto_nombre,
            eval_emp.legajo AS evaluador_legajo,
            eval_emp.apellido AS evaluador_apellido,
            eval_emp.nombre AS evaluador_nombre,
            u.usuario AS evaluador_usuario
        FROM skap_evaluaciones ev
        JOIN empleados emp ON emp.id = ev.empleado_id
        LEFT JOIN sectores sec ON sec.id = ev.sector_id
        LEFT JOIN sucursales suc ON suc.id = emp.sucursal_id
        LEFT JOIN puestos p ON p.id = ev.puesto_id
        LEFT JOIN empleados eval_emp ON eval_emp.id = ev.evaluador_empleado_id
        LEFT JOIN usuarios u ON u.id = ev.evaluador_usuario_id
    """


def _plan_select() -> str:
    return """
        SELECT
            p.id,
            p.evaluacion_id,
            p.empresa_id,
            p.empleado_id,
            p.sector_id,
            p.puesto_id,
            p.anio,
            p.promedio_general,
            p.nivel,
            p.observaciones,
            p.created_at,
            p.updated_at,
            ev.promedio_skills,
            ev.promedio_knowledge,
            ev.promedio_attitude,
            ev.promedio_performance,
            ev.fecha_evaluacion,
            ev.hora_evaluacion,
            emp.activo AS empleado_activo,
            emp.legajo AS empleado_legajo,
            emp.dni AS empleado_dni,
            emp.apellido AS empleado_apellido,
            emp.nombre AS empleado_nombre,
            emp.sucursal_id AS empleado_sucursal_id,
            sec.nombre AS sector_nombre,
            suc.nombre AS sucursal_nombre,
            pos.nombre AS puesto_nombre,
            eval_emp.apellido AS evaluador_apellido,
            eval_emp.nombre AS evaluador_nombre,
            (
                SELECT COUNT(*)
                FROM skap_planes_desarrollo_acciones a
                WHERE a.plan_id = p.id
            ) AS acciones_total,
            (
                SELECT COUNT(*)
                FROM skap_planes_desarrollo_acciones a
                WHERE a.plan_id = p.id AND a.estado = 'completado'
            ) AS acciones_completadas,
            (
                SELECT COUNT(*)
                FROM skap_planes_desarrollo_acciones a
                WHERE a.plan_id = p.id
                  AND a.estado IN ('pendiente', 'en_proceso')
                  AND a.fecha_compromiso IS NOT NULL
                  AND a.fecha_compromiso < CURDATE()
            ) AS acciones_vencidas
        FROM skap_planes_desarrollo p
        JOIN skap_evaluaciones ev ON ev.id = p.evaluacion_id
        JOIN empleados emp ON emp.id = p.empleado_id
        LEFT JOIN sectores sec ON sec.id = p.sector_id
        LEFT JOIN sucursales suc ON suc.id = emp.sucursal_id
        LEFT JOIN puestos pos ON pos.id = p.puesto_id
        LEFT JOIN empleados eval_emp ON eval_emp.id = ev.evaluador_empleado_id
    """


def get_evaluacion_by_id(evaluacion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_evaluation_select()}
            WHERE ev.id = %s
            LIMIT 1
            """,
            (int(evaluacion_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_evaluacion_by_empleado_anio(empleado_id: int, anio: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_evaluation_select()}
            WHERE ev.empleado_id = %s
              AND ev.anio = %s
            LIMIT 1
            """,
            (int(empleado_id), int(anio)),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_evaluaciones_page(
    page: int,
    per_page: int,
    *,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    sucursal_id: int | None = None,
    anio: int | None = None,
    search: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params: list = []
        scope_where, scope_params = _scope_filters(empresa_id=empresa_id, sector_id=sector_id, sucursal_id=sucursal_id)
        where.extend(scope_where)
        params.extend(scope_params)
        if anio:
            where.append("ev.anio = %s")
            params.append(int(anio))
        if search:
            like = f"%{search}%"
            where.append(
                "("
                "ev.empleado_nombre LIKE %s OR "
                "ev.empleado_legajo LIKE %s OR "
                "ev.empleado_dni LIKE %s OR "
                "ev.sector_nombre LIKE %s OR "
                "ev.evaluador_nombre LIKE %s OR "
                "ev.evaluador_usuario LIKE %s"
                ")"
            )
            params.extend([like, like, like, like, like, like])
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        offset = max(0, (int(page) - 1) * int(per_page))
        base = _evaluation_select()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM ({base}) ev
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        cursor.execute(
            f"""
            SELECT *
            FROM ({base}) ev
            {where_sql}
            ORDER BY ev.anio DESC, ev.promedio_general DESC, ev.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall() or []
        return rows, total
    finally:
        cursor.close()
        db.close()


def create_evaluacion(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO skap_evaluaciones
            (
                empresa_id,
                empleado_id,
                sector_id,
                puesto_id,
                anio,
                evaluador_empleado_id,
                evaluador_usuario_id,
                fecha_evaluacion,
                hora_evaluacion,
                promedio_skills,
                promedio_knowledge,
                promedio_attitude,
                promedio_performance,
                promedio_general,
                nivel,
                observaciones_generales,
                pdp_generado_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("empresa_id"),
                data.get("empleado_id"),
                data.get("sector_id"),
                data.get("puesto_id"),
                data.get("anio"),
                data.get("evaluador_empleado_id"),
                data.get("evaluador_usuario_id"),
                data.get("fecha_evaluacion"),
                data.get("hora_evaluacion"),
                data.get("promedio_skills"),
                data.get("promedio_knowledge"),
                data.get("promedio_attitude"),
                data.get("promedio_performance"),
                data.get("promedio_general"),
                data.get("nivel"),
                data.get("observaciones_generales"),
                data.get("pdp_generado_at"),
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_evaluacion_calculos(evaluacion_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_evaluaciones
            SET promedio_skills = %s,
                promedio_knowledge = %s,
                promedio_attitude = %s,
                promedio_performance = %s,
                promedio_general = %s,
                nivel = %s,
                observaciones_generales = %s,
                pdp_generado_at = %s
            WHERE id = %s
            """,
            (
                data.get("promedio_skills"),
                data.get("promedio_knowledge"),
                data.get("promedio_attitude"),
                data.get("promedio_performance"),
                data.get("promedio_general"),
                data.get("nivel"),
                data.get("observaciones_generales"),
                data.get("pdp_generado_at"),
                int(evaluacion_id),
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def create_evaluacion_detalles(evaluacion_id: int, detalles: list[dict]):
    db = get_db()
    cursor = db.cursor()
    try:
        for detalle in detalles:
            cursor.execute(
                """
                INSERT INTO skap_evaluaciones_detalle
                (
                    evaluacion_id,
                    pregunta_id,
                    categoria,
                    descripcion_snapshot,
                    peso_snapshot,
                    puntaje_esperado_snapshot,
                    puntaje_obtenido,
                    observacion,
                    evidencia,
                    cumple_esperado
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    int(evaluacion_id),
                    detalle.get("pregunta_id"),
                    str(detalle.get("categoria") or "").strip().upper(),
                    detalle.get("descripcion_snapshot"),
                    detalle.get("peso_snapshot"),
                    detalle.get("puntaje_esperado_snapshot"),
                    detalle.get("puntaje_obtenido"),
                    detalle.get("observacion"),
                    detalle.get("evidencia"),
                    1 if detalle.get("cumple_esperado") else 0,
                ),
            )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def get_evaluacion_detalles(evaluacion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM skap_evaluaciones_detalle
            WHERE evaluacion_id = %s
            ORDER BY categoria ASC, peso_snapshot DESC, descripcion_snapshot ASC, id ASC
            """,
            (int(evaluacion_id),),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def mark_pdp_generado(evaluacion_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_evaluaciones
            SET pdp_generado_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (int(evaluacion_id),),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def get_historial_empleado(empleado_id: int, *, empresa_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["ev.empleado_id = %s"]
        params: list = [int(empleado_id)]
        if empresa_id:
            where.append("ev.empresa_id = %s")
            params.append(int(empresa_id))
        cursor.execute(
            f"""
            SELECT
                ev.id,
                ev.anio,
                ev.promedio_general,
                ev.nivel,
                ev.sector_id,
                sec.nombre AS sector_nombre,
                ev.puesto_id,
                p.nombre AS puesto_nombre,
                ev.created_at
            FROM skap_evaluaciones ev
            LEFT JOIN sectores sec ON sec.id = ev.sector_id
            LEFT JOIN puestos p ON p.id = ev.puesto_id
            WHERE {" AND ".join(where)}
            ORDER BY ev.anio DESC, ev.id DESC
            """,
            tuple(params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_employee_ranking_rows(
    *,
    anio: int,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    limit: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["ev.anio = %s", "emp.activo = 1"]
        params: list = [int(anio)]
        if empresa_id:
            where.append("ev.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("ev.sector_id = %s")
            params.append(int(sector_id))
        limit_sql = f"LIMIT {int(limit)}" if limit else ""
        cursor.execute(
            f"""
            SELECT
                ev.id,
                ev.empleado_id,
                ev.empresa_id,
                ev.sector_id,
                ev.anio,
                ev.promedio_skills,
                ev.promedio_knowledge,
                ev.promedio_attitude,
                ev.promedio_performance,
                ev.promedio_general,
                ev.nivel,
                ev.fecha_evaluacion,
                emp.legajo,
                emp.dni,
                emp.apellido,
                emp.nombre,
                sec.nombre AS sector_nombre,
                p.nombre AS puesto_nombre
            FROM skap_evaluaciones ev
            JOIN empleados emp ON emp.id = ev.empleado_id
            LEFT JOIN sectores sec ON sec.id = ev.sector_id
            LEFT JOIN puestos p ON p.id = ev.puesto_id
            WHERE {" AND ".join(where)}
            ORDER BY ev.promedio_general DESC, ev.promedio_skills DESC, ev.promedio_knowledge DESC, ev.promedio_attitude DESC, ev.promedio_performance DESC, emp.apellido ASC, emp.nombre ASC, ev.id ASC
            {limit_sql}
            """,
            tuple(params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_sector_ranking_rows(
    *,
    anio: int,
    empresa_id: int | None = None,
    sector_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["ev.anio = %s", "emp.activo = 1"]
        params: list = [int(anio)]
        if empresa_id:
            where.append("ev.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("ev.sector_id = %s")
            params.append(int(sector_id))
        cursor.execute(
            f"""
            SELECT
                ev.sector_id,
                sec.nombre AS sector_nombre,
                COUNT(*) AS evaluaciones,
                ROUND(AVG(ev.promedio_general), 2) AS promedio_general,
                ROUND(AVG(ev.promedio_skills), 2) AS promedio_skills,
                ROUND(AVG(ev.promedio_knowledge), 2) AS promedio_knowledge,
                ROUND(AVG(ev.promedio_attitude), 2) AS promedio_attitude,
                ROUND(AVG(ev.promedio_performance), 2) AS promedio_performance
            FROM skap_evaluaciones ev
            JOIN empleados emp ON emp.id = ev.empleado_id
            LEFT JOIN sectores sec ON sec.id = ev.sector_id
            WHERE {" AND ".join(where)}
            GROUP BY ev.sector_id, sec.nombre
            ORDER BY promedio_general DESC, evaluaciones DESC, sec.nombre ASC
            """,
            tuple(params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_historical_evolution_rows(
    *,
    empresa_id: int | None = None,
    sector_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["emp.activo = 1"]
        params: list = []
        if empresa_id:
            where.append("ev.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("ev.sector_id = %s")
            params.append(int(sector_id))
        cursor.execute(
            f"""
            SELECT
                ev.anio,
                COUNT(*) AS evaluaciones,
                ROUND(AVG(ev.promedio_general), 2) AS promedio_general
            FROM skap_evaluaciones ev
            JOIN empleados emp ON emp.id = ev.empleado_id
            WHERE {" AND ".join(where)}
            GROUP BY ev.anio
            ORDER BY ev.anio ASC
            """,
            tuple(params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_category_averages_rows(
    *,
    anio: int | None = None,
    empresa_id: int | None = None,
    sector_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["emp.activo = 1"]
        params: list = []
        if anio:
            where.append("ev.anio = %s")
            params.append(int(anio))
        if empresa_id:
            where.append("ev.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("ev.sector_id = %s")
            params.append(int(sector_id))
        cursor.execute(
            f"""
            SELECT
                d.categoria,
                COUNT(*) AS respuestas,
                ROUND(AVG(d.puntaje_obtenido), 2) AS promedio_obtenido,
                ROUND(AVG(d.puntaje_esperado_snapshot), 2) AS promedio_esperado
            FROM skap_evaluaciones_detalle d
            JOIN skap_evaluaciones ev ON ev.id = d.evaluacion_id
            JOIN empleados emp ON emp.id = ev.empleado_id
            WHERE {" AND ".join(where)}
            GROUP BY d.categoria
            ORDER BY d.categoria ASC
            """,
            tuple(params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_question_averages_rows(
    *,
    anio: int | None = None,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    limit: int = 5,
    ascending: bool = True,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["emp.activo = 1"]
        params: list = []
        if anio:
            where.append("ev.anio = %s")
            params.append(int(anio))
        if empresa_id:
            where.append("ev.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("ev.sector_id = %s")
            params.append(int(sector_id))
        order = "ASC" if ascending else "DESC"
        cursor.execute(
            f"""
            SELECT
                d.pregunta_id,
                d.categoria,
                d.descripcion_snapshot,
                COUNT(*) AS respuestas,
                ROUND(AVG(d.puntaje_obtenido), 2) AS promedio_obtenido,
                ROUND(AVG(d.puntaje_esperado_snapshot), 2) AS promedio_esperado,
                ROUND(AVG(d.peso_snapshot), 2) AS peso_promedio
            FROM skap_evaluaciones_detalle d
            JOIN skap_evaluaciones ev ON ev.id = d.evaluacion_id
            JOIN empleados emp ON emp.id = ev.empleado_id
            WHERE {" AND ".join(where)}
            GROUP BY d.pregunta_id, d.categoria, d.descripcion_snapshot
            ORDER BY promedio_obtenido {order}, respuestas DESC, d.descripcion_snapshot ASC
            LIMIT %s
            """,
            (*params, int(limit)),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_dashboard_summary(
    *,
    anio: int,
    empresa_id: int | None = None,
    sector_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT
                COUNT(DISTINCT e.id) AS empleados_activos,
                COUNT(DISTINCT ev.empleado_id) AS empleados_evaluados,
                ROUND(AVG(ev.promedio_general), 2) AS promedio_general,
                ROUND(AVG(ev.promedio_skills), 2) AS promedio_skills,
                ROUND(AVG(ev.promedio_knowledge), 2) AS promedio_knowledge,
                ROUND(AVG(ev.promedio_attitude), 2) AS promedio_attitude,
                ROUND(AVG(ev.promedio_performance), 2) AS promedio_performance
            FROM empleados e
            LEFT JOIN skap_evaluaciones ev
              ON ev.empleado_id = e.id
             AND ev.anio = %s
             {"AND ev.empresa_id = %s" if empresa_id else ""}
             {"AND ev.sector_id = %s" if sector_id else ""}
            WHERE e.activo = 1
             {"AND e.empresa_id = %s" if empresa_id else ""}
             {"AND e.sector_id = %s" if sector_id else ""}
            """,
            tuple(
                [int(anio)]
                + ([int(empresa_id)] if empresa_id else [])
                + ([int(sector_id)] if sector_id else [])
                + ([int(empresa_id)] if empresa_id else [])
                + ([int(sector_id)] if sector_id else [])
            ),
        )
        emp_row = cursor.fetchone() or {}

        cursor.execute(
            f"""
            SELECT
                COUNT(DISTINCT p.id) AS planes_total,
                SUM(CASE WHEN a.estado = 'completado' THEN 1 ELSE 0 END) AS acciones_completadas,
                SUM(CASE WHEN a.estado = 'cancelado' THEN 1 ELSE 0 END) AS acciones_canceladas,
                SUM(CASE WHEN a.estado IN ('pendiente', 'en_proceso')
                          AND a.fecha_compromiso IS NOT NULL
                          AND a.fecha_compromiso < CURDATE()
                         THEN 1 ELSE 0 END) AS acciones_vencidas,
                SUM(CASE WHEN a.estado = 'pendiente' THEN 1 ELSE 0 END) AS acciones_pendientes,
                SUM(CASE WHEN a.estado = 'en_proceso' THEN 1 ELSE 0 END) AS acciones_en_proceso
            FROM skap_planes_desarrollo p
            LEFT JOIN skap_planes_desarrollo_acciones a ON a.plan_id = p.id
            WHERE p.anio = %s
            {"AND p.empresa_id = %s" if empresa_id else ""}
            {"AND p.sector_id = %s" if sector_id else ""}
            """,
            tuple([int(anio)] + ([int(empresa_id)] if empresa_id else []) + ([int(sector_id)] if sector_id else [])),
        )
        plan_row = cursor.fetchone() or {}

        return {
            "empleados_activos": int(emp_row.get("empleados_activos") or 0),
            "empleados_evaluados": int(emp_row.get("empleados_evaluados") or 0),
            "empleados_pendientes": max(0, int(emp_row.get("empleados_activos") or 0) - int(emp_row.get("empleados_evaluados") or 0)),
            "promedio_general": float(emp_row.get("promedio_general") or 0),
            "promedio_skills": float(emp_row.get("promedio_skills") or 0),
            "promedio_knowledge": float(emp_row.get("promedio_knowledge") or 0),
            "promedio_attitude": float(emp_row.get("promedio_attitude") or 0),
            "promedio_performance": float(emp_row.get("promedio_performance") or 0),
            "planes_total": int(plan_row.get("planes_total") or 0),
            "acciones_completadas": int(plan_row.get("acciones_completadas") or 0),
            "acciones_canceladas": int(plan_row.get("acciones_canceladas") or 0),
            "acciones_vencidas": int(plan_row.get("acciones_vencidas") or 0),
            "acciones_pendientes": int(plan_row.get("acciones_pendientes") or 0),
            "acciones_en_proceso": int(plan_row.get("acciones_en_proceso") or 0),
        }
    finally:
        cursor.close()
        db.close()


def get_plan_by_id(plan_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_plan_select()}
            WHERE p.id = %s
            LIMIT 1
            """,
            (int(plan_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_plan_by_evaluacion_id(evaluacion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            {_plan_select()}
            WHERE p.evaluacion_id = %s
            LIMIT 1
            """,
            (int(evaluacion_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_plan_by_empleado_anio(empleado_id: int, anio: int, *, empresa_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["p.empleado_id = %s", "p.anio = %s"]
        params: list = [int(empleado_id), int(anio)]
        if empresa_id:
            where.append("p.empresa_id = %s")
            params.append(int(empresa_id))
        cursor.execute(
            f"""
            {_plan_select()}
            WHERE {" AND ".join(where)}
            LIMIT 1
            """,
            tuple(params),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_planes_page(
    page: int,
    per_page: int,
    *,
    empresa_id: int | None = None,
    sector_id: int | None = None,
    sucursal_id: int | None = None,
    anio: int | None = None,
    search: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["emp.activo = 1"]
        params: list = []
        if empresa_id:
            where.append("p.empresa_id = %s")
            params.append(int(empresa_id))
        if sector_id:
            where.append("p.sector_id = %s")
            params.append(int(sector_id))
        if sucursal_id:
            where.append("p.empleado_sucursal_id = %s")
            params.append(int(sucursal_id))
        if anio:
            where.append("p.anio = %s")
            params.append(int(anio))
        if search:
            like = f"%{search}%"
            where.append(
                "("
                "p.empleado_nombre LIKE %s OR "
                "p.empleado_legajo LIKE %s OR "
                "p.sector_nombre LIKE %s OR "
                "p.evaluador_nombre LIKE %s"
                ")"
            )
            params.extend([like, like, like, like])
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        offset = max(0, (int(page) - 1) * int(per_page))
        base = _plan_select()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM ({base}) p
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        cursor.execute(
            f"""
            SELECT *
            FROM ({base}) p
            {where_sql}
            ORDER BY p.anio DESC, p.created_at DESC, p.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall() or []
        return rows, total
    finally:
        cursor.close()
        db.close()


def create_plan(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO skap_planes_desarrollo
            (
                evaluacion_id,
                empresa_id,
                empleado_id,
                sector_id,
                puesto_id,
                anio,
                promedio_general,
                nivel,
                observaciones
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("evaluacion_id"),
                data.get("empresa_id"),
                data.get("empleado_id"),
                data.get("sector_id"),
                data.get("puesto_id"),
                data.get("anio"),
                data.get("promedio_general"),
                data.get("nivel"),
                data.get("observaciones"),
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_plan(plan_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_planes_desarrollo
            SET observaciones = %s,
                promedio_general = %s,
                nivel = %s
            WHERE id = %s
            """,
            (
                data.get("observaciones"),
                data.get("promedio_general"),
                data.get("nivel"),
                int(plan_id),
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def get_plan_actions(plan_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.*,
                CASE
                    WHEN a.estado IN ('pendiente', 'en_proceso')
                         AND a.fecha_compromiso IS NOT NULL
                         AND a.fecha_compromiso < CURDATE()
                    THEN 'vencido'
                    ELSE a.estado
                END AS estado_actual,
                CONCAT(emp.apellido, ' ', emp.nombre) AS responsable_nombre,
                emp.legajo AS responsable_legajo
            FROM skap_planes_desarrollo_acciones a
            LEFT JOIN empleados emp ON emp.id = a.responsable_empleado_id
            WHERE a.plan_id = %s
            ORDER BY
                CASE
                    WHEN a.estado IN ('pendiente', 'en_proceso')
                         AND a.fecha_compromiso IS NOT NULL
                         AND a.fecha_compromiso < CURDATE()
                    THEN 1 ELSE 0
                END DESC,
                a.fecha_compromiso IS NULL ASC,
                a.fecha_compromiso ASC,
                a.created_at ASC,
                a.id ASC
            """,
            (int(plan_id),),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def get_plan_action_by_id(action_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.*,
                CASE
                    WHEN a.estado IN ('pendiente', 'en_proceso')
                         AND a.fecha_compromiso IS NOT NULL
                         AND a.fecha_compromiso < CURDATE()
                    THEN 'vencido'
                    ELSE a.estado
                END AS estado_actual,
                CONCAT(emp.apellido, ' ', emp.nombre) AS responsable_nombre,
                emp.legajo AS responsable_legajo
            FROM skap_planes_desarrollo_acciones a
            LEFT JOIN empleados emp ON emp.id = a.responsable_empleado_id
            WHERE a.id = %s
            LIMIT 1
            """,
            (int(action_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def add_plan_action(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO skap_planes_desarrollo_acciones
            (
                plan_id,
                categoria,
                accion,
                responsable_empleado_id,
                fecha_compromiso,
                estado,
                comentarios,
                completado_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("plan_id"),
                data.get("categoria"),
                data.get("accion"),
                data.get("responsable_empleado_id"),
                data.get("fecha_compromiso"),
                data.get("estado") or "pendiente",
                data.get("comentarios"),
                data.get("completado_at"),
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_plan_action(action_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_planes_desarrollo_acciones
            SET categoria = %s,
                accion = %s,
                responsable_empleado_id = %s,
                fecha_compromiso = %s,
                estado = %s,
                comentarios = %s,
                completado_at = %s
            WHERE id = %s
            """,
            (
                data.get("categoria"),
                data.get("accion"),
                data.get("responsable_empleado_id"),
                data.get("fecha_compromiso"),
                data.get("estado") or "pendiente",
                data.get("comentarios"),
                data.get("completado_at"),
                int(action_id),
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_plan_action_estado(action_id: int, estado: str, *, completado_at=None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE skap_planes_desarrollo_acciones
            SET estado = %s,
                completado_at = %s
            WHERE id = %s
            """,
            (estado, completado_at, int(action_id)),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete_plan_action(action_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM skap_planes_desarrollo_acciones
            WHERE id = %s
            """,
            (int(action_id),),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def get_pendientes_evaluacion(*, sector_id: int, anio: int, sucursal_id: int | None = None):
    """Empleados activos de un sector (opcionalmente filtrados por sucursal)
    que todavia no tienen evaluacion SKAP cargada para el anio indicado."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["e.activo = 1", "e.sector_id = %s"]
        params: list = [int(sector_id)]
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(int(sucursal_id))
        cursor.execute(
            f"""
            SELECT
                e.id,
                e.legajo,
                e.apellido,
                e.nombre,
                e.dni,
                e.sucursal_id,
                suc.nombre AS sucursal_nombre,
                e.puesto_id,
                p.nombre AS puesto_nombre,
                e.reporta_a_empleado_id,
                jefe.apellido AS jefe_apellido,
                jefe.nombre AS jefe_nombre
            FROM empleados e
            LEFT JOIN sucursales suc ON suc.id = e.sucursal_id
            LEFT JOIN puestos p ON p.id = e.puesto_id
            LEFT JOIN empleados jefe ON jefe.id = e.reporta_a_empleado_id
            LEFT JOIN skap_evaluaciones ev
              ON ev.empleado_id = e.id AND ev.anio = %s
            WHERE {" AND ".join(where)} AND ev.id IS NULL
            ORDER BY e.apellido ASC, e.nombre ASC
            """,
            (int(anio), *params),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()
