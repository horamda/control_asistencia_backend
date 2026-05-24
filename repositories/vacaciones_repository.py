from extensions import get_db


def get_empleado_for_vacaciones(empleado_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                id,
                empresa_id,
                dni,
                nombre,
                apellido,
                fecha_ingreso,
                fecha_baja,
                activo
            FROM empleados
            WHERE id = %s
            LIMIT 1
            """,
            (int(empleado_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def count_dias_efectivamente_trabajados(
    *,
    empleado_id: int,
    empresa_id: int,
    fecha_desde: str,
    fecha_hasta: str,
) -> int:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(DISTINCT fecha) AS total
            FROM asistencias
            WHERE empleado_id = %s
              AND empresa_id = %s
              AND fecha BETWEEN %s AND %s
              AND (
                  hora_entrada IS NOT NULL
                  OR hora_salida IS NOT NULL
                  OR LOWER(COALESCE(estado, '')) IN ('ok', 'tarde', 'salida_anticipada')
              )
            """,
            (int(empleado_id), int(empresa_id), fecha_desde, fecha_hasta),
        )
        row = cursor.fetchone() or {}
        return int(row.get("total") or 0)
    finally:
        cursor.close()
        db.close()


def get_movimientos_by_empleado_anio(*, empleado_id: int, empresa_id: int, anio: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                id,
                empleado_id,
                empresa_id,
                anio,
                tipo,
                dias,
                observacion,
                fecha_desde,
                fecha_hasta,
                estado,
                motivo_resolucion,
                resuelto_by,
                resuelto_at,
                origen_movimiento_id,
                revertido_por_movimiento_id,
                created_at,
                updated_at
            FROM vacaciones_movimientos
            WHERE empleado_id = %s
              AND empresa_id = %s
              AND anio = %s
            ORDER BY COALESCE(fecha_desde, DATE(created_at)) DESC, id DESC
            """,
            (int(empleado_id), int(empresa_id), int(anio)),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_movimiento_by_id(movimiento_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                vm.*,
                e.nombre,
                e.apellido,
                e.dni,
                emp.razon_social AS empresa_nombre
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
            WHERE vm.id = %s
            LIMIT 1
            """,
            (int(movimiento_id),),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_periodos_aprobados_page_by_empleado(
    empleado_id: int,
    page: int,
    per_page: int,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = [
            "vm.empleado_id = %s",
            "vm.tipo = 'tomado'",
            "vm.estado = 'aprobado'",
            "vm.revertido_por_movimiento_id IS NULL",
            "vm.origen_movimiento_id IS NULL",
        ]
        params = [int(empleado_id)]
        if fecha_desde:
            where.append("vm.fecha_hasta >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("vm.fecha_desde <= %s")
            params.append(fecha_hasta)
        where_sql = "WHERE " + " AND ".join(where)

        cursor.execute(
            f"""
            SELECT
                vm.id,
                vm.empresa_id,
                vm.empleado_id,
                vm.fecha_desde,
                vm.fecha_hasta,
                vm.observacion AS observaciones,
                e.nombre,
                e.apellido,
                e.dni,
                emp.razon_social AS empresa_nombre
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            LEFT JOIN empresas emp ON emp.id = vm.empresa_id
            {where_sql}
            ORDER BY vm.fecha_desde DESC, vm.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM vacaciones_movimientos vm
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_periodos_aprobados_all(limit: int = 5000):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                vm.id,
                vm.empresa_id,
                vm.empleado_id,
                vm.fecha_desde,
                vm.fecha_hasta,
                vm.observacion AS observaciones,
                e.nombre,
                e.apellido,
                e.dni,
                emp.razon_social AS empresa_nombre
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            LEFT JOIN empresas emp ON emp.id = vm.empresa_id
            WHERE vm.tipo = 'tomado'
              AND vm.estado = 'aprobado'
              AND vm.revertido_por_movimiento_id IS NULL
              AND vm.origen_movimiento_id IS NULL
            ORDER BY vm.fecha_desde DESC, vm.id DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def exists_movimiento_tomado_overlap(
    *,
    empleado_id: int,
    fecha_desde: str,
    fecha_hasta: str,
    exclude_movimiento_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        where = [
            "empleado_id = %s",
            "tipo = 'tomado'",
            "estado IN ('pendiente', 'aprobado')",
            "revertido_por_movimiento_id IS NULL",
            "origen_movimiento_id IS NULL",
            "fecha_desde <= %s",
            "fecha_hasta >= %s",
        ]
        params = [int(empleado_id), fecha_hasta, fecha_desde]
        if exclude_movimiento_id:
            where.append("id <> %s")
            params.append(int(exclude_movimiento_id))

        cursor.execute(
            f"""
            SELECT 1
            FROM vacaciones_movimientos
            WHERE {" AND ".join(where)}
            LIMIT 1
            """,
            tuple(params),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def _build_admin_filters(
    *,
    empleado_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    anio: int | None = None,
    mes: int | None = None,
):
    where = []
    params = []
    if empleado_id:
        where.append("vm.empleado_id = %s")
        params.append(int(empleado_id))
    if sector_id:
        where.append("e.sector_id = %s")
        params.append(int(sector_id))
    if search:
        like = f"%{search}%"
        where.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.dni LIKE %s)")
        params.extend([like, like, like])
    if estado:
        where.append("vm.estado = %s")
        params.append(estado)
    if tipo:
        where.append("vm.tipo = %s")
        params.append(tipo)
    if anio:
        where.append("vm.anio = %s")
        params.append(int(anio))
    if mes:
        if not anio:
            raise ValueError("Anio requerido para filtrar por mes.")
        month_start = f"{int(anio):04d}-{int(mes):02d}-01"
        if int(mes) == 12:
            next_month = f"{int(anio) + 1:04d}-01-01"
        else:
            next_month = f"{int(anio):04d}-{int(mes) + 1:02d}-01"
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
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def get_movimientos_page(
    page: int,
    per_page: int,
    *,
    empleado_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    anio: int | None = None,
    mes: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            sector_id=sector_id,
            search=search,
            estado=estado,
            tipo=tipo,
            anio=anio,
            mes=mes,
        )
        cursor.execute(
            f"""
            SELECT
                vm.*,
                e.nombre,
                e.apellido,
                e.dni,
                e.sector_id,
                sec.nombre AS sector_nombre,
                emp.razon_social AS empresa_nombre
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            {where_sql}
            ORDER BY vm.anio DESC, COALESCE(vm.fecha_desde, DATE(vm.created_at)) DESC, vm.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_movimientos_summary(
    *,
    empleado_id: int | None = None,
    sector_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    anio: int | None = None,
    mes: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            sector_id=sector_id,
            search=search,
            estado=estado,
            tipo=tipo,
            anio=anio,
            mes=mes,
        )
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN vm.estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes,
                SUM(CASE WHEN vm.estado = 'aprobado' THEN 1 ELSE 0 END) AS aprobados,
                SUM(CASE WHEN vm.estado = 'rechazado' THEN 1 ELSE 0 END) AS rechazados,
                SUM(CASE WHEN vm.revertido_por_movimiento_id IS NOT NULL THEN 1 ELSE 0 END) AS revertidos,
                COALESCE(SUM(CASE
                    WHEN vm.tipo = 'tomado'
                     AND vm.estado = 'aprobado'
                     AND vm.revertido_por_movimiento_id IS NULL
                     AND vm.origen_movimiento_id IS NULL
                    THEN vm.dias ELSE 0 END), 0) AS dias_tomados,
                COALESCE(SUM(CASE
                    WHEN vm.tipo = 'tomado'
                     AND vm.estado = 'pendiente'
                     AND vm.revertido_por_movimiento_id IS NULL
                     AND vm.origen_movimiento_id IS NULL
                    THEN vm.dias ELSE 0 END), 0) AS dias_pendientes,
                COALESCE(SUM(CASE
                    WHEN vm.tipo = 'compensatorio'
                     AND vm.estado = 'aprobado'
                     AND vm.revertido_por_movimiento_id IS NULL
                     AND vm.origen_movimiento_id IS NULL
                    THEN vm.dias ELSE 0 END), 0) AS dias_compensatorios,
                COALESCE(SUM(CASE
                    WHEN vm.tipo = 'ajuste'
                     AND vm.estado = 'aprobado'
                     AND vm.revertido_por_movimiento_id IS NULL
                     AND vm.origen_movimiento_id IS NULL
                    THEN vm.dias ELSE 0 END), 0) AS dias_ajustes
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
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
            "revertidos": int(row.get("revertidos") or 0),
            "dias_tomados": float(row.get("dias_tomados") or 0),
            "dias_pendientes": float(row.get("dias_pendientes") or 0),
            "dias_compensatorios": float(row.get("dias_compensatorios") or 0),
            "dias_ajustes": float(row.get("dias_ajustes") or 0),
        }
    finally:
        cursor.close()
        db.close()


def get_movimientos_export(**filters):
    rows, _total = get_movimientos_page(1, int(filters.pop("limit", 10000)), **filters)
    return rows


def update_movimiento_estado(
    movimiento_id: int,
    estado: str,
    *,
    actor_id: int | None = None,
    motivo: str | None = None,
    expected_estado: str | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        where_sql = "WHERE id = %s"
        params = [estado, actor_id, motivo, int(movimiento_id)]
        if expected_estado:
            where_sql += " AND estado = %s"
            params.append(expected_estado)
        cursor.execute(
            f"""
            UPDATE vacaciones_movimientos
            SET estado = %s,
                resuelto_by = %s,
                resuelto_at = NOW(),
                motivo_resolucion = %s
            {where_sql}
            """,
            tuple(params),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def update_movimiento(movimiento_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE vacaciones_movimientos
            SET empleado_id = %s,
                empresa_id = %s,
                anio = %s,
                tipo = %s,
                dias = %s,
                observacion = %s,
                fecha_desde = %s,
                fecha_hasta = %s,
                estado = %s
            WHERE id = %s
            """,
            (
                int(data["empleado_id"]),
                int(data["empresa_id"]),
                int(data["anio"]),
                data["tipo"],
                data["dias"],
                data.get("observacion"),
                data.get("fecha_desde"),
                data.get("fecha_hasta"),
                data.get("estado") or "pendiente",
                int(movimiento_id),
            ),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def mark_movimiento_revertido(
    movimiento_id: int,
    *,
    ajuste_id: int,
    actor_id: int | None = None,
    motivo: str | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE vacaciones_movimientos
            SET revertido_por_movimiento_id = %s,
                resuelto_by = %s,
                resuelto_at = NOW(),
                motivo_resolucion = %s
            WHERE id = %s
              AND revertido_por_movimiento_id IS NULL
            """,
            (int(ajuste_id), actor_id, motivo, int(movimiento_id)),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def get_movimientos_gantt_year(year: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        year_start = f"{int(year):04d}-01-01"
        year_end = f"{int(year):04d}-12-31"
        cursor.execute(
            """
            SELECT
                vm.id,
                vm.empleado_id,
                vm.empresa_id,
                vm.tipo,
                vm.estado,
                vm.dias,
                vm.fecha_desde,
                vm.fecha_hasta,
                vm.observacion,
                e.nombre,
                e.apellido,
                e.sector_id,
                sec.nombre AS sector_nombre
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            WHERE vm.tipo = 'tomado'
              AND vm.estado IN ('pendiente', 'aprobado')
              AND vm.revertido_por_movimiento_id IS NULL
              AND vm.origen_movimiento_id IS NULL
              AND vm.fecha_desde IS NOT NULL
              AND vm.fecha_hasta IS NOT NULL
              AND vm.fecha_desde <= %s
              AND vm.fecha_hasta >= %s
            ORDER BY e.apellido, e.nombre, vm.fecha_desde
            """,
            (year_end, year_start),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def create_movimiento(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO vacaciones_movimientos
            (
                empleado_id,
                empresa_id,
                anio,
                tipo,
                dias,
                observacion,
                fecha_desde,
                fecha_hasta,
                estado,
                origen_movimiento_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(data["empleado_id"]),
                int(data["empresa_id"]),
                int(data["anio"]),
                data["tipo"],
                data["dias"],
                data.get("observacion"),
                data.get("fecha_desde"),
                data.get("fecha_hasta"),
                data.get("estado") or "aprobado",
                data.get("origen_movimiento_id"),
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()
