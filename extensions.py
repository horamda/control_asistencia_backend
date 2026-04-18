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


def init_db():
    init_orm()
    _ensure_required_indexes()


def get_db():
    return get_raw_connection()
