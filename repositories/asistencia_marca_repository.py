from extensions import get_db


def create(
    *,
    empresa_id: int,
    empleado_id: int,
    fecha: str,
    hora: str,
    accion: str,
    metodo: str,
    tipo_marca: str,
    lat: float | None,
    lon: float | None,
    foto: str | None,
    gps_ok: bool | None,
    gps_distancia_m: float | None,
    gps_tolerancia_m: float | None,
    gps_ref_lat: float | None,
    gps_ref_lon: float | None,
    estado: str | None,
    observaciones: str | None = None,
    asistencia_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO asistencia_marcas (
                empresa_id,
                empleado_id,
                asistencia_id,
                fecha,
                hora,
                accion,
                metodo,
                tipo_marca,
                lat,
                lon,
                foto,
                gps_ok,
                gps_distancia_m,
                gps_tolerancia_m,
                gps_ref_lat,
                gps_ref_lon,
                estado,
                observaciones
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                empresa_id,
                empleado_id,
                asistencia_id,
                fecha,
                hora,
                accion,
                metodo,
                tipo_marca,
                lat,
                lon,
                foto,
                (1 if gps_ok else 0) if gps_ok is not None else None,
                gps_distancia_m,
                gps_tolerancia_m,
                gps_ref_lat,
                gps_ref_lon,
                estado,
                observaciones,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)
    finally:
        cursor.close()
        db.close()


def get_last_by_empleado_fecha(empleado_id: int, fecha: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM asistencia_marcas
            WHERE empleado_id = %s
              AND fecha = %s
            ORDER BY hora DESC, id DESC
            LIMIT 1
            """,
            (empleado_id, fecha),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def count_by_empleado_fecha(empleado_id: int, fecha: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM asistencia_marcas
            WHERE empleado_id = %s
              AND fecha = %s
            """,
            (empleado_id, fecha),
        )
        row = cursor.fetchone()
        return int(row["total"] if row else 0)
    finally:
        cursor.close()
        db.close()


def get_page_by_empleado(
    empleado_id: int,
    page: int,
    per_page: int,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = ["empleado_id = %s"]
        params = [empleado_id]
        if fecha_desde:
            where.append("fecha >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("fecha <= %s")
            params.append(fecha_hasta)
        where_sql = " AND ".join(where)

        cursor.execute(
            f"""
            SELECT
                id,
                asistencia_id,
                fecha,
                hora,
                accion,
                metodo,
                tipo_marca,
                lat,
                lon,
                gps_ok,
                gps_distancia_m,
                gps_tolerancia_m,
                estado,
                observaciones,
                fecha_creacion
            FROM asistencia_marcas
            WHERE {where_sql}
            ORDER BY fecha DESC, hora DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, per_page, offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM asistencia_marcas
            WHERE {where_sql}
            """,
            params,
        )
        total = int(cursor.fetchone()["total"])
        return rows, total
    finally:
        cursor.close()
        db.close()


def _build_admin_where(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    tipo_marca: str | None = None,
    accion: str | None = None,
    metodo: str | None = None,
    search: str | None = None,
    gps_ok: int | None = None,
):
    where = ["1=1"]
    params: list = []

    if empresa_id:
        where.append("am.empresa_id = %s")
        params.append(empresa_id)
    if empleado_id:
        where.append("am.empleado_id = %s")
        params.append(empleado_id)
    if fecha_desde:
        where.append("am.fecha >= %s")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("am.fecha <= %s")
        params.append(fecha_hasta)
    if tipo_marca:
        where.append("am.tipo_marca = %s")
        params.append(tipo_marca)
    if accion:
        where.append("am.accion = %s")
        params.append(accion)
    if metodo:
        where.append("am.metodo = %s")
        params.append(metodo)
    if search:
        like = f"%{search}%"
        where.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.dni LIKE %s)")
        params.extend([like, like, like])
    if gps_ok in (0, 1):
        where.append("am.gps_ok = %s")
        params.append(gps_ok)

    return " AND ".join(where), params


def get_page_admin(
    *,
    page: int,
    per_page: int,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    tipo_marca: str | None = None,
    accion: str | None = None,
    metodo: str | None = None,
    search: str | None = None,
    gps_ok: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where_sql, params = _build_admin_where(
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            tipo_marca=tipo_marca,
            accion=accion,
            metodo=metodo,
            search=search,
            gps_ok=gps_ok,
        )

        cursor.execute(
            f"""
            SELECT
                am.id,
                am.empresa_id,
                am.empleado_id,
                am.asistencia_id,
                am.fecha,
                am.hora,
                am.accion,
                am.metodo,
                am.tipo_marca,
                am.lat,
                am.lon,
                am.gps_ok,
                am.gps_distancia_m,
                am.gps_tolerancia_m,
                am.estado,
                am.observaciones,
                am.fecha_creacion,
                e.apellido,
                e.nombre,
                e.dni,
                emp.razon_social AS empresa_nombre
            FROM asistencia_marcas am
            JOIN empleados e ON e.id = am.empleado_id
            JOIN empresas emp ON emp.id = am.empresa_id
            WHERE {where_sql}
            ORDER BY am.fecha DESC, am.hora DESC, am.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, per_page, offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM asistencia_marcas am
            JOIN empleados e ON e.id = am.empleado_id
            JOIN empresas emp ON emp.id = am.empresa_id
            WHERE {where_sql}
            """,
            params,
        )
        total = int(cursor.fetchone()["total"])
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_for_export_admin(
    *,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    tipo_marca: str | None = None,
    accion: str | None = None,
    metodo: str | None = None,
    search: str | None = None,
    gps_ok: int | None = None,
    limit: int = 5000,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql, params = _build_admin_where(
            empresa_id=empresa_id,
            empleado_id=empleado_id,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            tipo_marca=tipo_marca,
            accion=accion,
            metodo=metodo,
            search=search,
            gps_ok=gps_ok,
        )

        cursor.execute(
            f"""
            SELECT
                am.id,
                am.empresa_id,
                am.empleado_id,
                am.asistencia_id,
                am.fecha,
                am.hora,
                am.accion,
                am.metodo,
                am.tipo_marca,
                am.lat,
                am.lon,
                am.gps_ok,
                am.gps_distancia_m,
                am.gps_tolerancia_m,
                am.estado,
                am.observaciones,
                am.fecha_creacion,
                e.apellido,
                e.nombre,
                e.dni,
                emp.razon_social AS empresa_nombre
            FROM asistencia_marcas am
            JOIN empleados e ON e.id = am.empleado_id
            JOIN empresas emp ON emp.id = am.empresa_id
            WHERE {where_sql}
            ORDER BY am.fecha DESC, am.hora DESC, am.id DESC
            LIMIT %s
            """,
            (*params, max(1, min(limit, 20000))),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def backfill_from_asistencias():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO asistencia_marcas (
                empresa_id,
                empleado_id,
                asistencia_id,
                fecha,
                hora,
                accion,
                metodo,
                tipo_marca,
                lat,
                lon,
                foto,
                gps_ok,
                gps_distancia_m,
                gps_tolerancia_m,
                gps_ref_lat,
                gps_ref_lon,
                estado,
                observaciones,
                fecha_creacion
            )
            SELECT
                a.empresa_id,
                a.empleado_id,
                a.id AS asistencia_id,
                a.fecha,
                a.hora_entrada AS hora,
                'ingreso' AS accion,
                COALESCE(a.metodo_entrada, 'manual') AS metodo,
                'jornada' AS tipo_marca,
                a.lat_entrada AS lat,
                a.lon_entrada AS lon,
                a.foto_entrada AS foto,
                a.gps_ok_entrada AS gps_ok,
                a.gps_distancia_entrada_m AS gps_distancia_m,
                a.gps_tolerancia_entrada_m AS gps_tolerancia_m,
                a.gps_ref_lat_entrada AS gps_ref_lat,
                a.gps_ref_lon_entrada AS gps_ref_lon,
                a.estado,
                a.observaciones,
                a.created_at AS fecha_creacion
            FROM asistencias a
            WHERE a.hora_entrada IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM asistencia_marcas am
                WHERE am.asistencia_id = a.id
                  AND am.accion = 'ingreso'
              )
            """
        )
        inserted_ingresos = cursor.rowcount

        cursor.execute(
            """
            INSERT INTO asistencia_marcas (
                empresa_id,
                empleado_id,
                asistencia_id,
                fecha,
                hora,
                accion,
                metodo,
                tipo_marca,
                lat,
                lon,
                foto,
                gps_ok,
                gps_distancia_m,
                gps_tolerancia_m,
                gps_ref_lat,
                gps_ref_lon,
                estado,
                observaciones,
                fecha_creacion
            )
            SELECT
                a.empresa_id,
                a.empleado_id,
                a.id AS asistencia_id,
                a.fecha,
                a.hora_salida AS hora,
                'egreso' AS accion,
                COALESCE(a.metodo_salida, 'manual') AS metodo,
                'jornada' AS tipo_marca,
                a.lat_salida AS lat,
                a.lon_salida AS lon,
                a.foto_salida AS foto,
                a.gps_ok_salida AS gps_ok,
                a.gps_distancia_salida_m AS gps_distancia_m,
                a.gps_tolerancia_salida_m AS gps_tolerancia_m,
                a.gps_ref_lat_salida AS gps_ref_lat,
                a.gps_ref_lon_salida AS gps_ref_lon,
                a.estado,
                a.observaciones,
                a.created_at AS fecha_creacion
            FROM asistencias a
            WHERE a.hora_salida IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM asistencia_marcas am
                WHERE am.asistencia_id = a.id
                  AND am.accion = 'egreso'
              )
            """
        )
        inserted_egresos = cursor.rowcount

        db.commit()
        return inserted_ingresos, inserted_egresos
    finally:
        cursor.close()
        db.close()
