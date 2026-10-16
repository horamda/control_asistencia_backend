"""Reuniones: una fecha puede tener un horario propio (reprogramada a mano), que se conserva al editar
la reunion o al cambiar el calendario de dias no laborables."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column


def migrate_cursor(cursor):
    if not _has_column(cursor, "reunion_ocurrencias", "reprogramada"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD COLUMN reprogramada TINYINT NOT NULL DEFAULT 0 AFTER estado")


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
