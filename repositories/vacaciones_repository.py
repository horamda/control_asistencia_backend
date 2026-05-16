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


def _build_admin_filters(
    *,
    empleado_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    anio: int | None = None,
):
    where = []
    params = []
    if empleado_id:
        where.append("vm.empleado_id = %s")
        params.append(int(empleado_id))
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
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def get_movimientos_page(
    page: int,
    per_page: int,
    *,
    empleado_id: int | None = None,
    search: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    anio: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            tipo=tipo,
            anio=anio,
        )
        cursor.execute(
            f"""
            SELECT
                vm.*,
                e.nombre,
                e.apellido,
                e.dni,
                emp.razon_social AS empresa_nombre
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
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
    search: str | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    anio: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_admin_filters(
            empleado_id=empleado_id,
            search=search,
            estado=estado,
            tipo=tipo,
            anio=anio,
        )
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN vm.estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes,
                SUM(CASE WHEN vm.estado = 'aprobado' THEN 1 ELSE 0 END) AS aprobados,
                SUM(CASE WHEN vm.estado = 'rechazado' THEN 1 ELSE 0 END) AS rechazados,
                COALESCE(SUM(CASE WHEN vm.tipo = 'tomado' AND vm.estado = 'aprobado' THEN vm.dias ELSE 0 END), 0) AS dias_tomados,
                COALESCE(SUM(CASE WHEN vm.tipo = 'tomado' AND vm.estado = 'pendiente' THEN vm.dias ELSE 0 END), 0) AS dias_pendientes,
                COALESCE(SUM(CASE WHEN vm.tipo = 'compensatorio' AND vm.estado = 'aprobado' THEN vm.dias ELSE 0 END), 0) AS dias_compensatorios,
                COALESCE(SUM(CASE WHEN vm.tipo = 'ajuste' AND vm.estado = 'aprobado' THEN vm.dias ELSE 0 END), 0) AS dias_ajustes
            FROM vacaciones_movimientos vm
            JOIN empleados e ON e.id = vm.empleado_id
            JOIN empresas emp ON emp.id = vm.empresa_id
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


def update_movimiento_estado(movimiento_id: int, estado: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE vacaciones_movimientos
            SET estado = %s
            WHERE id = %s
            """,
            (estado, int(movimiento_id)),
        )
        db.commit()
        return cursor.rowcount > 0
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
                estado
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()
