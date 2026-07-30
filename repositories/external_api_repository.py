from extensions import get_db


def _in_clause(values: list) -> str:
    return ",".join(["%s"] * len(values))


def _normalize_name_filters(values: list[str] | None) -> list[str]:
    normalized = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip().lower()
        if not text:
            continue
        variants = [text]
        if text.endswith("es") and len(text) > 3:
            variants.append(text[:-2])
        if text.endswith("s") and len(text) > 2:
            variants.append(text[:-1])
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                normalized.append(variant)
    return normalized


def get_empresas(*, activa: int | None = 1):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ""
        params = []
        if activa in (0, 1):
            where = "WHERE activa = %s"
            params.append(int(activa))
        cursor.execute(
            f"""
            SELECT
                id,
                razon_social,
                nombre_fantasia,
                cuit,
                email,
                telefono,
                direccion,
                activa
            FROM empresas
            {where}
            ORDER BY razon_social
            """,
            params,
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_sucursales(*, empresa_id: int | None = None, activa: int | None = 1):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if empresa_id:
            where.append("s.empresa_id = %s")
            params.append(int(empresa_id))
        if activa in (0, 1):
            where.append("s.activa = %s")
            params.append(int(activa))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(
            f"""
            SELECT
                s.id,
                s.empresa_id,
                e.razon_social AS empresa_nombre,
                s.nombre,
                s.direccion,
                s.latitud,
                s.longitud,
                s.radio_permitido_m,
                s.activa
            FROM sucursales s
            JOIN empresas e ON e.id = s.empresa_id
            {where_sql}
            ORDER BY e.razon_social, s.nombre
            """,
            params,
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def list_empleados(
    *,
    page: int = 1,
    per_page: int = 100,
    empresa_id: int | None = None,
    sucursal_ids: list[int] | None = None,
    sucursal_nombres: list[str] | None = None,
    estados: list[str] | None = None,
    activo: int | None = 1,
    puesto_ids: list[int] | None = None,
    puesto_nombres: list[str] | None = None,
    search: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (max(page, 1) - 1) * per_page
        where = []
        params = []

        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(int(empresa_id))

        sucursal_ids = [int(v) for v in (sucursal_ids or []) if v]
        if sucursal_ids:
            where.append(f"e.sucursal_id IN ({_in_clause(sucursal_ids)})")
            params.extend(sucursal_ids)

        sucursal_nombres = _normalize_name_filters(sucursal_nombres)
        if sucursal_nombres:
            where.append(f"LOWER(TRIM(s.nombre)) IN ({_in_clause(sucursal_nombres)})")
            params.extend(sucursal_nombres)

        estados = [str(v).strip().lower() for v in (estados or []) if str(v).strip()]
        if estados:
            where.append(f"LOWER(TRIM(e.estado)) IN ({_in_clause(estados)})")
            params.extend(estados)
        elif activo in (0, 1):
            where.append("e.activo = %s")
            params.append(int(activo))

        puesto_ids = [int(v) for v in (puesto_ids or []) if v]
        puesto_nombres = _normalize_name_filters(puesto_nombres)
        puesto_filters = []
        puesto_params = []
        if puesto_ids:
            puesto_filters.append(f"e.puesto_id IN ({_in_clause(puesto_ids)})")
            puesto_params.extend(puesto_ids)
            puesto_filters.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM empleado_puestos ep
                    WHERE ep.empleado_id = e.id
                      AND ep.activo = 1
                      AND ep.puesto_id IN ({_in_clause(puesto_ids)})
                )
                """
            )
            puesto_params.extend(puesto_ids)
        if puesto_nombres:
            puesto_filters.append(
                f"LOWER(TRIM(p.nombre)) IN ({_in_clause(puesto_nombres)})"
            )
            puesto_params.extend(puesto_nombres)
            puesto_filters.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM empleado_puestos ep
                    JOIN puestos pa ON pa.id = ep.puesto_id
                    WHERE ep.empleado_id = e.id
                      AND ep.activo = 1
                      AND LOWER(TRIM(pa.nombre)) IN ({_in_clause(puesto_nombres)})
                )
                """
            )
            puesto_params.extend(puesto_nombres)
        if puesto_filters:
            where.append("(" + " OR ".join(puesto_filters) + ")")
            params.extend(puesto_params)

        if search:
            like = f"%{search.strip()}%"
            where.append(
                """
                (
                    e.apellido LIKE %s OR
                    e.nombre LIKE %s OR
                    e.dni LIKE %s OR
                    e.legajo LIKE %s
                )
                """
            )
            params.extend([like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        from_sql = f"""
            FROM empleados e
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN puestos p ON p.id = e.puesto_id
            LEFT JOIN localidades l ON l.codigo_postal = e.codigo_postal
            LEFT JOIN empleados jefe ON jefe.id = e.reporta_a_empleado_id
            LEFT JOIN (
                SELECT
                    ep.empleado_id,
                    GROUP_CONCAT(DISTINCT pa.id ORDER BY pa.nombre SEPARATOR ',') AS puestos_adicionales_ids,
                    GROUP_CONCAT(DISTINCT pa.nombre ORDER BY pa.nombre SEPARATOR ', ') AS puestos_adicionales_nombres
                FROM empleado_puestos ep
                JOIN puestos pa ON pa.id = ep.puesto_id
                WHERE ep.activo = 1
                GROUP BY ep.empleado_id
            ) extras ON extras.empleado_id = e.id
            {where_sql}
        """

        cursor.execute(
            f"""
            SELECT
                e.id,
                e.empresa_id,
                emp.razon_social AS empresa_nombre,
                e.sucursal_id,
                s.nombre AS sucursal_nombre,
                e.sector_id,
                sec.nombre AS sector_nombre,
                e.puesto_id,
                p.nombre AS puesto_nombre,
                extras.puestos_adicionales_ids,
                extras.puestos_adicionales_nombres,
                e.reporta_a_empleado_id,
                CONCAT(TRIM(COALESCE(jefe.apellido, '')), ' ', TRIM(COALESCE(jefe.nombre, ''))) AS reporta_a_nombre,
                e.legajo,
                e.dni,
                e.cuil,
                e.nombre,
                e.apellido,
                e.email,
                e.telefono,
                e.fecha_ingreso,
                e.fecha_baja,
                e.tipo_contrato,
                e.modalidad,
                e.categoria,
                e.cod_chess_erp,
                e.estado,
                e.activo,
                e.codigo_postal,
                l.localidad AS localidad_nombre
            {from_sql}
            ORDER BY emp.razon_social, s.nombre, e.apellido, e.nombre
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), int(offset)),
        )
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total {from_sql}", params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def list_justificaciones(
    *,
    page: int = 1,
    per_page: int = 100,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    estado: str | None = None,
    search: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (max(page, 1) - 1) * per_page
        where = []
        params = []
        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(int(empresa_id))
        if empleado_id:
            where.append("j.empleado_id = %s")
            params.append(int(empleado_id))
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(int(sucursal_id))
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(int(sector_id))
        if fecha_desde:
            where.append("COALESCE(j.fecha_hasta, j.fecha) >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("COALESCE(j.fecha_desde, j.fecha) <= %s")
            params.append(fecha_hasta)
        if estado:
            where.append("j.estado = %s")
            params.append(estado)
        if search:
            like = f"%{search.strip()}%"
            where.append(
                """
                (
                    e.apellido LIKE %s OR
                    e.nombre LIKE %s OR
                    e.dni LIKE %s OR
                    e.legajo LIKE %s OR
                    j.motivo LIKE %s
                )
                """
            )
            params.extend([like, like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        from_sql = f"""
            FROM justificaciones j
            JOIN empleados e ON e.id = j.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN usuarios u ON u.id = j.resuelto_by_usuario_id
            {where_sql}
        """

        cursor.execute(
            f"""
            SELECT
                j.id,
                j.empleado_id,
                e.empresa_id,
                emp.razon_social AS empresa_nombre,
                e.sucursal_id,
                s.nombre AS sucursal_nombre,
                e.sector_id,
                sec.nombre AS sector_nombre,
                e.legajo,
                e.dni,
                e.apellido,
                e.nombre,
                j.asistencia_id,
                a.fecha AS asistencia_fecha,
                j.fecha,
                j.fecha_desde,
                j.fecha_hasta,
                j.motivo,
                j.archivo,
                j.estado,
                j.resuelto_by_usuario_id,
                u.usuario AS resuelto_by_usuario,
                j.resuelto_at,
                j.comentario_resolucion,
                j.motivo_rechazo,
                j.notificado_empleado_at,
                j.visto_por_empleado_at,
                j.created_at,
                (
                    SELECT COUNT(*)
                    FROM legajo_eventos le
                    JOIN legajo_evento_adjuntos adj
                      ON adj.evento_id = le.id
                     AND adj.estado = 'activo'
                    WHERE le.justificacion_id = j.id
                ) AS adjuntos_count
            {from_sql}
            ORDER BY j.created_at DESC, j.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), int(offset)),
        )
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total {from_sql}", tuple(params))
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def list_vacaciones_movimientos(
    *,
    page: int = 1,
    per_page: int = 100,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    search: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (max(page, 1) - 1) * per_page
        where = []
        params = []
        if empresa_id:
            where.append("vm.empresa_id = %s")
            params.append(int(empresa_id))
        if empleado_id:
            where.append("vm.empleado_id = %s")
            params.append(int(empleado_id))
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(int(sucursal_id))
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(int(sector_id))
        if anio:
            where.append("vm.anio = %s")
            params.append(int(anio))
        if mes:
            if not anio:
                raise ValueError("anio requerido para filtrar por mes.")
            month_start = f"{int(anio):04d}-{int(mes):02d}-01"
            next_month = f"{int(anio) + 1:04d}-01-01" if int(mes) == 12 else f"{int(anio):04d}-{int(mes) + 1:02d}-01"
            where.append(
                """
                (
                    (
                        vm.fecha_desde IS NOT NULL
                        AND vm.fecha_hasta IS NOT NULL
                        AND vm.fecha_desde < %s
                        AND vm.fecha_hasta >= %s
                    )
                    OR (
                        vm.fecha_desde IS NULL
                        AND vm.fecha_hasta IS NULL
                        AND vm.created_at >= %s
                        AND vm.created_at < %s
                    )
                )
                """
            )
            params.extend([next_month, month_start, month_start, next_month])
        if fecha_desde:
            where.append("COALESCE(vm.fecha_hasta, DATE(vm.created_at)) >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("COALESCE(vm.fecha_desde, DATE(vm.created_at)) <= %s")
            params.append(fecha_hasta)
        if estado:
            where.append("vm.estado = %s")
            params.append(estado)
        if tipo:
            where.append("vm.tipo = %s")
            params.append(tipo)
        if search:
            like = f"%{search.strip()}%"
            where.append(
                """
                (
                    e.apellido LIKE %s OR
                    e.nombre LIKE %s OR
                    e.dni LIKE %s OR
                    e.legajo LIKE %s OR
                    vm.observacion LIKE %s
                )
                """
            )
            params.extend([like, like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        from_sql = f"""
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN empleados rb ON rb.id = vm.resuelto_by
            {where_sql}
        """

        cursor.execute(
            f"""
            SELECT
                vm.id,
                vm.empleado_id,
                vm.empresa_id,
                emp.razon_social AS empresa_nombre,
                e.sucursal_id,
                s.nombre AS sucursal_nombre,
                e.sector_id,
                sec.nombre AS sector_nombre,
                e.legajo,
                e.dni,
                e.apellido,
                e.nombre,
                vm.anio,
                vm.tipo,
                vm.dias,
                vm.observacion,
                vm.fecha_desde,
                vm.fecha_hasta,
                vm.estado,
                vm.motivo_resolucion,
                vm.resuelto_by,
                CONCAT(TRIM(COALESCE(rb.apellido, '')), ' ', TRIM(COALESCE(rb.nombre, ''))) AS resuelto_by_nombre,
                vm.resuelto_at,
                vm.origen_movimiento_id,
                vm.revertido_por_movimiento_id,
                vm.created_at,
                vm.updated_at
            {from_sql}
            ORDER BY vm.anio DESC, COALESCE(vm.fecha_desde, DATE(vm.created_at)) DESC, vm.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), int(offset)),
        )
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total {from_sql}", tuple(params))
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()
