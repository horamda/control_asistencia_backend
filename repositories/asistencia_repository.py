from extensions import get_db


def _get_empresa_id_for_empleado(cursor, empleado_id: int | None):
    if not empleado_id:
        return None
    cursor.execute("""
        SELECT empresa_id
        FROM empleados
        WHERE id = %s
        LIMIT 1
    """, (empleado_id,))
    row = cursor.fetchone()
    if isinstance(row, dict):
        return row.get("empresa_id")
    return row[0] if row else None


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT a.*, e.nombre, e.apellido, emp.razon_social AS empresa_nombre
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            ORDER BY a.fecha DESC, a.id DESC
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(page: int, per_page: int, empleado_id: int | None = None, fecha_desde: str | None = None, fecha_hasta: str | None = None, search: str | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if empleado_id:
            where.append("a.empleado_id = %s")
            params.append(empleado_id)
        if fecha_desde:
            where.append("a.fecha >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("a.fecha <= %s")
            params.append(fecha_hasta)
        if search:
            where.append("(e.apellido LIKE %s OR e.nombre LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"""
            SELECT a.*, e.nombre, e.apellido, emp.razon_social AS empresa_nombre
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            {where_sql}
            ORDER BY a.fecha DESC, a.id DESC
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            {where_sql}
        """, params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(asistencia_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM asistencias
            WHERE id = %s
        """, (asistencia_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_empleado_fecha(empleado_id: int, fecha: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (empleado_id, fecha),
        )
        return cursor.fetchone()
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
                fecha,
                hora_entrada,
                hora_salida,
                estado,
                observaciones,
                metodo_entrada,
                metodo_salida,
                gps_ok_entrada,
                gps_ok_salida,
                gps_distancia_entrada_m,
                gps_distancia_salida_m,
                gps_tolerancia_entrada_m,
                gps_tolerancia_salida_m
            FROM asistencias
            WHERE {where_sql}
            ORDER BY fecha DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, per_page, offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM asistencias
            WHERE {where_sql}
            """,
            params,
        )
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def exists_for_empleado_fecha(empleado_id: int, fecha: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT 1
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha = %s
            LIMIT 1
        """, (empleado_id, fecha))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def create_ausente(empleado_id: int, fecha: str, observaciones: str | None = None):
    db = get_db()
    cursor = db.cursor()
    try:
        empresa_id = _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")
        cursor.execute("""
            INSERT INTO asistencias (empresa_id, empleado_id, fecha, estado, observaciones)
            VALUES (%s,%s,%s,%s,%s)
        """, (empresa_id, empleado_id, fecha, "ausente", observaciones))
        db.commit()
        return cursor.lastrowid
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
        cursor.execute("""
            INSERT INTO asistencias
            (
                empresa_id,
                empleado_id,
                fecha,
                hora_entrada,
                hora_salida,
                lat_entrada,
                lon_entrada,
                lat_salida,
                lon_salida,
                foto_entrada,
                foto_salida,
                metodo_entrada,
                metodo_salida,
                estado,
                observaciones
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            empresa_id,
            empleado_id,
            data.get("fecha") or None,
            data.get("hora_entrada") or None,
            data.get("hora_salida") or None,
            data.get("lat_entrada"),
            data.get("lon_entrada"),
            data.get("lat_salida"),
            data.get("lon_salida"),
            data.get("foto_entrada"),
            data.get("foto_salida"),
            data.get("metodo_entrada"),
            data.get("metodo_salida"),
            data.get("estado"),
            data.get("observaciones")
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def register_entrada(
    empleado_id: int,
    fecha: str,
    hora_entrada: str,
    metodo_entrada: str,
    lat_entrada: float | None,
    lon_entrada: float | None,
    foto_entrada: str | None,
    estado: str,
    observaciones: str | None = None,
    gps_ok_entrada: bool | None = None,
    gps_distancia_entrada_m: float | None = None,
    gps_tolerancia_entrada_m: float | None = None,
    gps_ref_lat_entrada: float | None = None,
    gps_ref_lon_entrada: float | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        empresa_id = _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")

        cursor.execute(
            """
            SELECT *
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (empleado_id, fecha),
        )
        row = cursor.fetchone()
        if row:
            if row.get("hora_entrada") is not None:
                raise ValueError("Entrada ya registrada para esa fecha.")
            cursor.execute(
                """
                UPDATE asistencias
                SET hora_entrada = %s,
                    lat_entrada = %s,
                    lon_entrada = %s,
                    gps_ok_entrada = %s,
                    gps_distancia_entrada_m = %s,
                    gps_tolerancia_entrada_m = %s,
                    gps_ref_lat_entrada = %s,
                    gps_ref_lon_entrada = %s,
                    foto_entrada = %s,
                    metodo_entrada = %s,
                    estado = %s,
                    observaciones = %s
                WHERE id = %s
                """,
                (
                    hora_entrada,
                    lat_entrada,
                    lon_entrada,
                    (1 if gps_ok_entrada else 0) if gps_ok_entrada is not None else None,
                    gps_distancia_entrada_m,
                    gps_tolerancia_entrada_m,
                    gps_ref_lat_entrada,
                    gps_ref_lon_entrada,
                    foto_entrada,
                    metodo_entrada,
                    estado,
                    observaciones if observaciones is not None else row.get("observaciones"),
                    row["id"],
                ),
            )
            asistencia_id = row["id"]
        else:
            cursor.execute(
                """
                INSERT INTO asistencias
                (
                    empresa_id,
                    empleado_id,
                    fecha,
                    hora_entrada,
                    lat_entrada,
                    lon_entrada,
                    gps_ok_entrada,
                    gps_distancia_entrada_m,
                    gps_tolerancia_entrada_m,
                    gps_ref_lat_entrada,
                    gps_ref_lon_entrada,
                    foto_entrada,
                    metodo_entrada,
                    estado,
                    observaciones
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    empresa_id,
                    empleado_id,
                    fecha,
                    hora_entrada,
                    lat_entrada,
                    lon_entrada,
                    (1 if gps_ok_entrada else 0) if gps_ok_entrada is not None else None,
                    gps_distancia_entrada_m,
                    gps_tolerancia_entrada_m,
                    gps_ref_lat_entrada,
                    gps_ref_lon_entrada,
                    foto_entrada,
                    metodo_entrada,
                    estado,
                    observaciones,
                ),
            )
            asistencia_id = cursor.lastrowid

        db.commit()
        return asistencia_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def register_salida(
    empleado_id: int,
    fecha: str,
    hora_salida: str,
    metodo_salida: str,
    lat_salida: float | None,
    lon_salida: float | None,
    foto_salida: str | None,
    estado: str,
    observaciones: str | None = None,
    gps_ok_salida: bool | None = None,
    gps_distancia_salida_m: float | None = None,
    gps_tolerancia_salida_m: float | None = None,
    gps_ref_lat_salida: float | None = None,
    gps_ref_lon_salida: float | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        cursor.execute(
            """
            SELECT *
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (empleado_id, fecha),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("No hay fichada de entrada para esa fecha.")
        if row.get("hora_salida") is not None:
            raise ValueError("Salida ya registrada para esa fecha.")

        cursor.execute(
            """
            UPDATE asistencias
            SET hora_salida = %s,
                lat_salida = %s,
                lon_salida = %s,
                gps_ok_salida = %s,
                gps_distancia_salida_m = %s,
                gps_tolerancia_salida_m = %s,
                gps_ref_lat_salida = %s,
                gps_ref_lon_salida = %s,
                foto_salida = %s,
                metodo_salida = %s,
                estado = %s,
                observaciones = %s
            WHERE id = %s
            """,
            (
                hora_salida,
                lat_salida,
                lon_salida,
                (1 if gps_ok_salida else 0) if gps_ok_salida is not None else None,
                gps_distancia_salida_m,
                gps_tolerancia_salida_m,
                gps_ref_lat_salida,
                gps_ref_lon_salida,
                foto_salida,
                metodo_salida,
                estado,
                observaciones if observaciones is not None else row.get("observaciones"),
                row["id"],
            ),
        )
        db.commit()
        return row["id"]
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def upsert_resumen_desde_marca(
    empleado_id: int,
    fecha: str,
    hora: str,
    accion: str,
    metodo: str,
    lat: float | None,
    lon: float | None,
    foto: str | None,
    estado: str,
    observaciones: str | None = None,
    gps_ok: bool | None = None,
    gps_distancia_m: float | None = None,
    gps_tolerancia_m: float | None = None,
    gps_ref_lat: float | None = None,
    gps_ref_lon: float | None = None,
):
    if accion not in {"ingreso", "egreso"}:
        raise ValueError("accion invalida")

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        empresa_id = _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")

        cursor.execute(
            """
            SELECT *
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (empleado_id, fecha),
        )
        row = cursor.fetchone()

        if not row:
            if accion != "ingreso":
                raise ValueError("No hay fichada de entrada para esa fecha.")
            cursor.execute(
                """
                INSERT INTO asistencias
                (
                    empresa_id,
                    empleado_id,
                    fecha,
                    hora_entrada,
                    lat_entrada,
                    lon_entrada,
                    gps_ok_entrada,
                    gps_distancia_entrada_m,
                    gps_tolerancia_entrada_m,
                    gps_ref_lat_entrada,
                    gps_ref_lon_entrada,
                    foto_entrada,
                    metodo_entrada,
                    estado,
                    observaciones
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    empresa_id,
                    empleado_id,
                    fecha,
                    hora,
                    lat,
                    lon,
                    (1 if gps_ok else 0) if gps_ok is not None else None,
                    gps_distancia_m,
                    gps_tolerancia_m,
                    gps_ref_lat,
                    gps_ref_lon,
                    foto,
                    metodo,
                    estado,
                    observaciones,
                ),
            )
            asistencia_id = cursor.lastrowid
            db.commit()
            return asistencia_id

        asistencia_id = row["id"]
        if accion == "ingreso":
            if row.get("hora_salida") is None and row.get("hora_entrada") is not None:
                raise ValueError("Ya hay un ingreso abierto para esa fecha.")

            if row.get("hora_entrada") is None:
                cursor.execute(
                    """
                    UPDATE asistencias
                    SET hora_entrada = %s,
                        lat_entrada = %s,
                        lon_entrada = %s,
                        gps_ok_entrada = %s,
                        gps_distancia_entrada_m = %s,
                        gps_tolerancia_entrada_m = %s,
                        gps_ref_lat_entrada = %s,
                        gps_ref_lon_entrada = %s,
                        foto_entrada = %s,
                        metodo_entrada = %s,
                        hora_salida = NULL,
                        lat_salida = NULL,
                        lon_salida = NULL,
                        gps_ok_salida = NULL,
                        gps_distancia_salida_m = NULL,
                        gps_tolerancia_salida_m = NULL,
                        gps_ref_lat_salida = NULL,
                        gps_ref_lon_salida = NULL,
                        foto_salida = NULL,
                        metodo_salida = NULL,
                        estado = %s,
                        observaciones = %s
                    WHERE id = %s
                    """,
                    (
                        hora,
                        lat,
                        lon,
                        (1 if gps_ok else 0) if gps_ok is not None else None,
                        gps_distancia_m,
                        gps_tolerancia_m,
                        gps_ref_lat,
                        gps_ref_lon,
                        foto,
                        metodo,
                        estado,
                        observaciones if observaciones is not None else row.get("observaciones"),
                        asistencia_id,
                    ),
                )
            else:
                # El registro mas reciente ya esta cerrado; para soportar mas de un ciclo
                # en el mismo dia creamos una nueva asistencia.
                cursor.execute(
                    """
                    INSERT INTO asistencias
                    (
                        empresa_id,
                        empleado_id,
                        fecha,
                        hora_entrada,
                        lat_entrada,
                        lon_entrada,
                        gps_ok_entrada,
                        gps_distancia_entrada_m,
                        gps_tolerancia_entrada_m,
                        gps_ref_lat_entrada,
                        gps_ref_lon_entrada,
                        foto_entrada,
                        metodo_entrada,
                        estado,
                        observaciones
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        empresa_id,
                        empleado_id,
                        fecha,
                        hora,
                        lat,
                        lon,
                        (1 if gps_ok else 0) if gps_ok is not None else None,
                        gps_distancia_m,
                        gps_tolerancia_m,
                        gps_ref_lat,
                        gps_ref_lon,
                        foto,
                        metodo,
                        estado,
                        observaciones,
                    ),
                )
                asistencia_id = cursor.lastrowid
        else:
            if row.get("hora_entrada") is None or row.get("hora_salida") is not None:
                cursor.execute(
                    """
                    SELECT *
                    FROM asistencias
                    WHERE empleado_id = %s
                      AND fecha = %s
                      AND hora_entrada IS NOT NULL
                      AND hora_salida IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (empleado_id, fecha),
                )
                row_abierta = cursor.fetchone()
                if not row_abierta:
                    raise ValueError("No hay fichada de entrada para esa fecha.")
                row = row_abierta
                asistencia_id = row["id"]
            cursor.execute(
                """
                UPDATE asistencias
                SET hora_salida = %s,
                    lat_salida = %s,
                    lon_salida = %s,
                    gps_ok_salida = %s,
                    gps_distancia_salida_m = %s,
                    gps_tolerancia_salida_m = %s,
                    gps_ref_lat_salida = %s,
                    gps_ref_lon_salida = %s,
                    foto_salida = %s,
                    metodo_salida = %s,
                    estado = %s,
                    observaciones = %s
                WHERE id = %s
                """,
                (
                    hora,
                    lat,
                    lon,
                    (1 if gps_ok else 0) if gps_ok is not None else None,
                    gps_distancia_m,
                    gps_tolerancia_m,
                    gps_ref_lat,
                    gps_ref_lon,
                    foto,
                    metodo,
                    estado,
                    observaciones if observaciones is not None else row.get("observaciones"),
                    asistencia_id,
                ),
            )

        db.commit()
        return asistencia_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def update(asistencia_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        empleado_id = data.get("empleado_id")
        empresa_id = data.get("empresa_id") or _get_empresa_id_for_empleado(cursor, empleado_id)
        if not empresa_id:
            raise ValueError("Empleado invalido o sin empresa asignada.")
        cursor.execute("""
            UPDATE asistencias
            SET
                empresa_id = %s,
                empleado_id = %s,
                fecha = %s,
                hora_entrada = %s,
                hora_salida = %s,
                lat_entrada = %s,
                lon_entrada = %s,
                lat_salida = %s,
                lon_salida = %s,
                foto_entrada = %s,
                foto_salida = %s,
                metodo_entrada = %s,
                metodo_salida = %s,
                estado = %s,
                observaciones = %s
            WHERE id = %s
        """, (
            empresa_id,
            empleado_id,
            data.get("fecha") or None,
            data.get("hora_entrada") or None,
            data.get("hora_salida") or None,
            data.get("lat_entrada"),
            data.get("lon_entrada"),
            data.get("lat_salida"),
            data.get("lon_salida"),
            data.get("foto_entrada"),
            data.get("foto_salida"),
            data.get("metodo_entrada"),
            data.get("metodo_salida"),
            data.get("estado"),
            data.get("observaciones"),
            asistencia_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(asistencia_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM asistencias
            WHERE id = %s
        """, (asistencia_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
