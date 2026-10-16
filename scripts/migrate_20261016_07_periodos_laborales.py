"""Historial de periodos laborales por empleado (bajas y reingresos).

Cada fila es un periodo trabajado: fecha_desde (NULL = sin fecha de ingreso
cargada) hasta fecha_hasta inclusive (NULL = sigue vigente). Las estadisticas
cuentan un registro solo si cae dentro de algun periodo del empleado.
"""

TABLE = """
CREATE TABLE IF NOT EXISTS empleado_periodos_laborales (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id  INT          NOT NULL,
  fecha_desde  DATE         NULL,
  fecha_hasta  DATE         NULL,
  created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_periodos_laborales_empleado (empleado_id, fecha_desde, fecha_hasta)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Un periodo por empleado a partir de los datos actuales:
# - activos: desde el ingreso; la baja solo se respeta si es futura (egreso
#   programado), porque una baja pasada en un activo es un dato viejo.
# - inactivos con fecha de baja: desde el ingreso hasta la baja.
# - inactivos sin fecha de baja: sin periodo; quedan fuera de las estadisticas
#   hasta que se cargue la fecha (no se infiere de la ultima fichada).
BACKFILL = """
INSERT INTO empleado_periodos_laborales (empleado_id, fecha_desde, fecha_hasta)
SELECT
    e.id,
    CASE
        WHEN e.activo = 0 AND e.fecha_ingreso > e.fecha_baja THEN NULL
        ELSE e.fecha_ingreso
    END,
    CASE
        WHEN e.activo = 1 AND e.fecha_baja >= CURDATE() AND e.fecha_baja >= COALESCE(e.fecha_ingreso, e.fecha_baja)
            THEN e.fecha_baja
        WHEN e.activo = 1 THEN NULL
        ELSE e.fecha_baja
    END
FROM empleados e
WHERE (e.activo = 1 OR e.fecha_baja IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM empleado_periodos_laborales p WHERE p.empleado_id = e.id)
"""


# El boton Desactivar viejo solo tocaba `activo`: alinear el estado para que
# guardar el formulario no reactive (y reabra el periodo) por error.
ESTADO_INACTIVOS = """
UPDATE empleados
SET estado = 'inactivo'
WHERE activo = 0 AND (estado IS NULL OR estado IN ('activo', 'eventual'))
"""


def migrate_cursor(cursor):
    cursor.execute(TABLE)
    cursor.execute(BACKFILL)
    cursor.execute(ESTADO_INACTIVOS)


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
