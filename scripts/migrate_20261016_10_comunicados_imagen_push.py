"""Comunicados: version 2:1 de la imagen para la notificacion push (Android la muestra apaisada)."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column


def migrate_cursor(cursor):
    if not _has_column(cursor, "comunicados", "imagen_push"):
        cursor.execute("ALTER TABLE comunicados ADD COLUMN imagen_push MEDIUMBLOB NULL AFTER imagen")


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
