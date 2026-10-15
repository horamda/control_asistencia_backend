"""Reuniones que se posponen por feriado.

Los feriados y dias no laborables viven en asistencia_dias_no_laborables (el calendario del reporte
mensual): aca solo se agregan la accion por reunion y el registro del cambio en cada ocurrencia.
migrate_unificar mueve a ese calendario lo que se haya cargado en la tabla feriados (version previa) y
la elimina."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column, _values


def migrate_cursor(cursor):
    if not _has_column(cursor, "reuniones", "feriado_accion"):
        cursor.execute("ALTER TABLE reuniones ADD COLUMN feriado_accion VARCHAR(10) NOT NULL DEFAULT 'posponer'"
                       " AFTER qr_version")
    if not _has_column(cursor, "reunion_ocurrencias", "fecha_original"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD COLUMN fecha_original DATE NULL AFTER fecha")
    if not _has_column(cursor, "reunion_ocurrencias", "motivo_cambio"):
        cursor.execute("ALTER TABLE reunion_ocurrencias ADD COLUMN motivo_cambio VARCHAR(255) NULL AFTER motivo_cancelacion")


def migrate_unificar(cursor):
    cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'feriados'")
    if not int(_values(cursor.fetchone())[0]):
        return
    cursor.execute(
        """
        INSERT IGNORE INTO asistencia_dias_no_laborables
          (empresa_id, sucursal_id, sector_id, fecha, motivo, created_by_usuario_id)
        SELECT empresa_id, sucursal_id, 0, fecha, nombre, creado_por FROM feriados
        """
    )
    cursor.execute(
        """
        UPDATE asistencia_dias_no_laborables d
        JOIN feriados f ON f.empresa_id = d.empresa_id AND f.sucursal_id = d.sucursal_id AND f.fecha = d.fecha
        SET d.motivo = f.nombre
        WHERE d.sector_id = 0 AND (d.motivo IS NULL OR d.motivo = '')
        """
    )
    cursor.execute("DROP TABLE feriados")


if __name__ == "__main__":
    from db import init_orm
    from extensions import get_db
    init_orm()
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(cursor)
        migrate_unificar(cursor)
        connection.commit()
    finally:
        cursor.close()
        connection.close()
