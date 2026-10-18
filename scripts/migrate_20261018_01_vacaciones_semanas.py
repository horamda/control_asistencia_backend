"""Vacaciones por semanas (services/vacaciones_semanas_service.py).

- solicitud_id: agrupa las tandas (movimientos) de un mismo pedido. NULL en lo cargado antes: la solicitud de un
  movimiento viejo es el propio movimiento (COALESCE(solicitud_id, id)).
- resuelto_por_empleado_id: quien aprobo o rechazo desde la app (jefe directo). resuelto_by sigue siendo el usuario
  del panel.
- cancelacion_pedida_at / cancelacion_motivo: el empleado pidio dar de baja unas vacaciones ya aprobadas; lo resuelve
  su jefe o RR. HH.

Solo agrega columnas e indices (nada se borra ni se recalcula). Idempotente.
Reversion: las columnas nuevas se pueden dejar; el codigo anterior no las usa."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column, _has_index

COLUMNAS = (
    ("solicitud_id", "ALTER TABLE vacaciones_movimientos ADD COLUMN solicitud_id BIGINT UNSIGNED NULL AFTER id"),
    ("resuelto_por_empleado_id",
     "ALTER TABLE vacaciones_movimientos ADD COLUMN resuelto_por_empleado_id INT NULL AFTER motivo_resolucion"),
    ("cancelacion_pedida_at",
     "ALTER TABLE vacaciones_movimientos ADD COLUMN cancelacion_pedida_at DATETIME NULL AFTER resuelto_por_empleado_id"),
    ("cancelacion_motivo",
     "ALTER TABLE vacaciones_movimientos ADD COLUMN cancelacion_motivo VARCHAR(255) NULL AFTER cancelacion_pedida_at"),
)


def migrate_cursor(cursor):
    for columna, sql in COLUMNAS:
        if not _has_column(cursor, "vacaciones_movimientos", columna):
            cursor.execute(sql)
    if not _has_index(cursor, "vacaciones_movimientos", "idx_vac_mov_solicitud"):
        cursor.execute("ALTER TABLE vacaciones_movimientos ADD KEY idx_vac_mov_solicitud (solicitud_id)")
    # Tandas del equipo y recordatorios: por empresa, tipo, estado y fecha de inicio.
    if not _has_index(cursor, "vacaciones_movimientos", "idx_vac_mov_empresa_desde"):
        cursor.execute("ALTER TABLE vacaciones_movimientos ADD KEY idx_vac_mov_empresa_desde (empresa_id, tipo, estado, fecha_desde)")


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
