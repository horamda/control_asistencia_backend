from db import get_raw_connection, init_orm


REQUIRED_INDEXES = {
    "empleado_horarios": {
        "idx_eh_empleado_rango": "(empleado_id, fecha_desde, fecha_hasta)",
        "idx_eh_horario": "(horario_id)",
    },
    "asistencias": {
        "idx_asis_empleado_fecha": "(empleado_id, fecha)",
        "idx_asis_empresa_fecha": "(empresa_id, fecha)",
    },
    "empleado_excepciones": {
        "idx_ex_emp_fecha": "(empleado_id, fecha)",
        "idx_ex_emp_empresa_fecha": "(empresa_id, fecha)",
    },
    "justificaciones": {
        "idx_justificaciones_empleado_fecha": "(empleado_id, fecha, estado)",
        "idx_justificaciones_empleado_fechas": "(empleado_id, fecha_desde, fecha_hasta, estado)",
    },
}


def _ensure_required_indexes():
    conn = get_raw_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        for table, indexes in REQUIRED_INDEXES.items():
            # Usar backticks para quoting de identificadores SQL (nombres de tabla/índice
            # son constantes internas, pero el quoting es buena práctica defensiva).
            cursor.execute(f"SHOW INDEX FROM `{table}`")
            existing = {row["Key_name"] for row in cursor.fetchall()}
            for name, cols in indexes.items():
                if name in existing:
                    continue
                cursor.execute(f"CREATE INDEX `{name}` ON `{table}` {cols}")
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cursor.fetchone() is not None


def _column_nullable(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT IS_NULLABLE
        FROM information_schema.COLUMNS
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    )
    row = cursor.fetchone()
    return bool(row and str(row.get("IS_NULLABLE") or "").upper() == "YES")


def _ensure_justificaciones_schema():
    conn = get_raw_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        fecha_exists = _column_exists(cursor, "justificaciones", "fecha")
        fecha_desde_exists = _column_exists(cursor, "justificaciones", "fecha_desde")
        fecha_hasta_exists = _column_exists(cursor, "justificaciones", "fecha_hasta")

        if not fecha_exists:
            cursor.execute(
                "ALTER TABLE justificaciones ADD COLUMN fecha DATE NULL AFTER asistencia_id"
            )
            fecha_exists = True

        if not fecha_desde_exists:
            after_clause = "AFTER fecha" if fecha_exists else "AFTER asistencia_id"
            cursor.execute(
                f"ALTER TABLE justificaciones ADD COLUMN fecha_desde DATE NULL {after_clause}"
            )
            fecha_desde_exists = True

        if not fecha_hasta_exists:
            after_clause = "AFTER fecha_desde" if fecha_desde_exists else "AFTER fecha"
            cursor.execute(
                f"ALTER TABLE justificaciones ADD COLUMN fecha_hasta DATE NULL {after_clause}"
            )
            fecha_hasta_exists = True

        cursor.execute("SET @old_safe_updates := @@SQL_SAFE_UPDATES")
        cursor.execute("SET SQL_SAFE_UPDATES = 0")
        try:
            if fecha_exists:
                cursor.execute(
                    """
                    UPDATE justificaciones j
                    LEFT JOIN asistencias a ON a.id = j.asistencia_id
                    SET j.fecha = COALESCE(j.fecha, a.fecha, DATE(j.created_at))
                    WHERE j.fecha IS NULL
                    """
                )

            if fecha_desde_exists or fecha_hasta_exists:
                cursor.execute(
                    """
                    UPDATE justificaciones
                    SET
                        fecha_desde = COALESCE(fecha_desde, fecha),
                        fecha_hasta = COALESCE(fecha_hasta, fecha)
                    WHERE fecha_desde IS NULL
                       OR fecha_hasta IS NULL
                    """
                )
        finally:
            cursor.execute("SET SQL_SAFE_UPDATES = @old_safe_updates")

        if fecha_exists and _column_nullable(cursor, "justificaciones", "fecha"):
            cursor.execute("ALTER TABLE justificaciones MODIFY fecha DATE NOT NULL")

        if _column_nullable(cursor, "justificaciones", "fecha_desde") or _column_nullable(
            cursor, "justificaciones", "fecha_hasta"
        ):
            cursor.execute(
                "ALTER TABLE justificaciones MODIFY fecha_desde DATE NOT NULL, MODIFY fecha_hasta DATE NOT NULL"
            )

        conn.commit()
    finally:
        cursor.close()
        conn.close()


def init_db():
    init_orm()
    _ensure_justificaciones_schema()
    _ensure_required_indexes()


def get_db():
    return get_raw_connection()
