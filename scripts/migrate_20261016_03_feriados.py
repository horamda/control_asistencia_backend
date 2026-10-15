"""Calendario de feriados (nacionales, de la empresa o de una sucursal) y reuniones que se posponen.

feriados.sucursal_id = 0 aplica a todas las sucursales (evita NULL en la clave unica)."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column


def migrate_cursor(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS feriados (
          id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
          empresa_id  INT          NOT NULL,
          sucursal_id INT          NOT NULL DEFAULT 0,
          fecha       DATE         NOT NULL,
          nombre      VARCHAR(150) NOT NULL,
          tipo        VARCHAR(20)  NOT NULL DEFAULT 'empresa',
          origen      VARCHAR(12)  NOT NULL DEFAULT 'manual',
          creado_por  INT          NULL,
          created_at  DATETIME     NOT NULL,
          PRIMARY KEY (id),
          UNIQUE KEY uk_feriados_fecha (empresa_id, sucursal_id, fecha),
          KEY idx_feriados_fecha (empresa_id, fecha)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    if not _has_column(cursor, "reuniones", "feriado_accion"):
        cursor.execute("ALTER TABLE reuniones ADD COLUMN feriado_accion VARCHAR(10) NOT NULL DEFAULT 'posponer'"
                       " AFTER qr_version")
    if not _has_column(cursor, "reunion_ocurrencias", "fecha_original"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD COLUMN fecha_original DATE NULL AFTER fecha")
    if not _has_column(cursor, "reunion_ocurrencias", "motivo_cambio"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD COLUMN motivo_cambio VARCHAR(255) NULL AFTER motivo_cancelacion")


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
