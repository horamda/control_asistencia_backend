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
