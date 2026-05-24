import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table_name, index_name),
    )
    return cursor.fetchone() is not None


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str):
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _ensure_index(cursor, table_name: str, index_name: str, ddl: str):
    if not _index_exists(cursor, table_name, index_name):
        cursor.execute(ddl)


BACKFILL_SQL = """
INSERT INTO vacaciones_movimientos
(
  empleado_id,
  empresa_id,
  anio,
  tipo,
  dias,
  observacion,
  fecha_desde,
  fecha_hasta,
  estado,
  origen_movimiento_id,
  revertido_por_movimiento_id
)
SELECT
  v.empleado_id,
  COALESCE(v.empresa_id, e.empresa_id) AS empresa_id,
  YEAR(v.fecha_desde) AS anio,
  'tomado' AS tipo,
  DATEDIFF(v.fecha_hasta, v.fecha_desde) + 1 AS dias,
  NULLIF(v.observaciones, '') AS observacion,
  v.fecha_desde,
  v.fecha_hasta,
  'aprobado' AS estado,
  NULL AS origen_movimiento_id,
  NULL AS revertido_por_movimiento_id
FROM vacaciones v
JOIN empleados e ON e.id = v.empleado_id
WHERE v.fecha_desde IS NOT NULL
  AND v.fecha_hasta IS NOT NULL
  AND v.fecha_desde <= v.fecha_hasta
  AND COALESCE(v.empresa_id, e.empresa_id) IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM vacaciones_movimientos vm
    WHERE vm.empleado_id = v.empleado_id
      AND vm.tipo = 'tomado'
      AND vm.fecha_desde = v.fecha_desde
      AND vm.fecha_hasta = v.fecha_hasta
      AND vm.estado IN ('pendiente', 'aprobado')
    LIMIT 1
  )
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        _ensure_column(
            cursor,
            "vacaciones_movimientos",
            "motivo_resolucion",
            "motivo_resolucion VARCHAR(255) NULL AFTER estado",
        )
        _ensure_column(
            cursor,
            "vacaciones_movimientos",
            "resuelto_by",
            "resuelto_by INT NULL AFTER motivo_resolucion",
        )
        _ensure_column(
            cursor,
            "vacaciones_movimientos",
            "resuelto_at",
            "resuelto_at DATETIME NULL AFTER resuelto_by",
        )
        _ensure_column(
            cursor,
            "vacaciones_movimientos",
            "origen_movimiento_id",
            "origen_movimiento_id BIGINT UNSIGNED NULL AFTER resuelto_at",
        )
        _ensure_column(
            cursor,
            "vacaciones_movimientos",
            "revertido_por_movimiento_id",
            "revertido_por_movimiento_id BIGINT UNSIGNED NULL AFTER origen_movimiento_id",
        )
        _ensure_index(
            cursor,
            "vacaciones_movimientos",
            "idx_vac_mov_periodos_aprobados",
            "CREATE INDEX idx_vac_mov_periodos_aprobados ON vacaciones_movimientos (tipo, estado, fecha_desde, fecha_hasta)",
        )
        _ensure_index(
            cursor,
            "vacaciones_movimientos",
            "idx_vac_mov_origen",
            "CREATE INDEX idx_vac_mov_origen ON vacaciones_movimientos (origen_movimiento_id)",
        )
        _ensure_index(
            cursor,
            "vacaciones_movimientos",
            "idx_vac_mov_revertido",
            "CREATE INDEX idx_vac_mov_revertido ON vacaciones_movimientos (revertido_por_movimiento_id)",
        )
        cursor.execute(BACKFILL_SQL)
        db.commit()
        print("[done] migration 20260519_01_vacaciones_movimientos_fuente_principal")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
