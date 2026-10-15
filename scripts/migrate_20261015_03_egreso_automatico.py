"""Egreso automatico por olvido de fichada: parametros por empresa.

configuracion_empresa.egreso_automatico_activo (1 por defecto) y
egreso_automatico_horas (8 por defecto): horas que se suman al ingreso cuando
el empleado no tiene horario asignado para ese dia.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

COLUMNS = {
    "egreso_automatico_activo": "TINYINT(1) NOT NULL DEFAULT 1",
    "egreso_automatico_horas": "DECIMAL(4,2) NOT NULL DEFAULT 8.00",
}


def _first(row):
    return list(row.values())[0] if isinstance(row, dict) else row[0]


def migrate_cursor(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME='configuracion_empresa'"
    )
    if not _first(cursor.fetchone()):
        return  # esquemas minimos (tests): la tabla la crean migraciones anteriores
    for name, definition in COLUMNS.items():
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME='configuracion_empresa' AND COLUMN_NAME=%s",
            (name,),
        )
        if not _first(cursor.fetchone()):
            cursor.execute(f"ALTER TABLE configuracion_empresa ADD COLUMN {name} {definition}")


def migrate_metodo_salida(cursor):
    """asistencias.metodo_salida es ENUM: se agrega 'automatico' al final
    (conserva los valores existentes; en MySQL es un cambio solo de metadatos)."""
    cursor.execute(
        "SELECT COLUMN_TYPE, IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME='asistencias' AND COLUMN_NAME='metodo_salida'"
    )
    row = cursor.fetchone()
    if not row:
        return
    column_type, nullable = (list(row.values()) if isinstance(row, dict) else list(row))[:2]
    if isinstance(column_type, (bytes, bytearray)):
        column_type = column_type.decode("utf-8")
    if not str(column_type).lower().startswith("enum(") or "'automatico'" in str(column_type):
        return  # texto libre o ya migrado
    nuevo = str(column_type)[:-1] + ",'automatico')"
    cursor.execute(
        f"ALTER TABLE asistencias MODIFY metodo_salida {nuevo} {'NULL' if nullable == 'YES' else 'NOT NULL'}"
    )


if __name__ == "__main__":
    from db import init_orm
    from extensions import get_db
    init_orm()
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(cursor)
        migrate_metodo_salida(cursor)
        connection.commit()
        print("Parametros de egreso automatico instalados.")
    finally:
        cursor.close()
        connection.close()
