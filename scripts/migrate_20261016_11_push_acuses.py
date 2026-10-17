"""Push: la app confirma cuando el aviso llega al celular (recibido_at) y cuando lo tocan (abierto_at)."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column


def migrate_cursor(cursor):
    if not _has_column(cursor, "push_envios", "recibido_at"):
        cursor.execute("ALTER TABLE push_envios ADD COLUMN recibido_at DATETIME NULL AFTER enviado_at")
    if not _has_column(cursor, "push_envios", "abierto_at"):
        cursor.execute("ALTER TABLE push_envios ADD COLUMN abierto_at DATETIME NULL AFTER recibido_at")


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
