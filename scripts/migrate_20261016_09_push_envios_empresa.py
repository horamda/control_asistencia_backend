"""Historial de avisos automaticos en Comunicados: indice para listar push_envios por empresa y fecha."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_index


def migrate_cursor(cursor):
    if not _has_index(cursor, "push_envios", "idx_push_envios_empresa"):
        cursor.execute("ALTER TABLE push_envios ADD KEY idx_push_envios_empresa (empresa_id, creado_at)")


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
