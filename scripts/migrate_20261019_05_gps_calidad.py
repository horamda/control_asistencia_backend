"""Calidad de la ubicacion de cada fichada (contrato mobile 1.54.0).

Agrega a asistencia_marcas tres columnas opcionales que manda la app desde su version que las soporte:
- gps_precision_m: precision informada por el telefono, en metros (margen de error de la posicion).
- gps_simulada: 1 si el sistema operativo marco la posicion como simulada (app de GPS falso), 0 si no.
- gps_edad_s: cuantos segundos tenia la posicion al fichar (una ultima posicion conocida puede ser vieja).

Solo agrega columnas NULL (en MySQL 8 es instantaneo): no toca datos existentes ni cambia la validacion del radio.
Reversion: DROP de las tres columnas y DELETE de la version 20261019_gps_calidad en app_schema_versions."""


def _values(row):
    return list(row.values()) if isinstance(row, dict) else list(row)


def _has_column(cursor, table, column):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND COLUMN_NAME = %s", (table, column))
    return int(_values(cursor.fetchone())[0]) > 0


COLUMNAS = (
    ("gps_precision_m", "DECIMAL(8,1) NULL"),
    ("gps_simulada", "TINYINT NULL"),
    ("gps_edad_s", "INT NULL"),
)


def migrate_cursor(cursor):
    for columna, tipo in COLUMNAS:
        if not _has_column(cursor, "asistencia_marcas", columna):
            cursor.execute(f"ALTER TABLE asistencia_marcas ADD COLUMN {columna} {tipo}")


if __name__ == "__main__":
    from db import init_orm
    from extensions import get_db
    init_orm()
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(cursor)
        connection.commit()
    finally:
        cursor.close()
        connection.close()
