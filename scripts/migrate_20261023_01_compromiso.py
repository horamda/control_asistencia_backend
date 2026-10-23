"""Indice de compromiso (engagement): un porcentaje por empresa, año, sucursal y sector (area).

sucursal_id = 0: toda la empresa (con sector_id = 0). sector_id = 0: toda la sucursal. Si no se carga el total de una
sucursal o de la empresa, se calcula como el promedio de sus sectores. Se carga desde el panel (Excel o a mano) y la
app lo lee en /api/v1/mobile/me/compromiso.

Reversion: DROP TABLE compromiso_indices y borrar la version 20261023_compromiso de app_schema_versions."""

TABLA = """
CREATE TABLE IF NOT EXISTS compromiso_indices (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id      INT          NOT NULL,
  anio            SMALLINT     NOT NULL,
  sucursal_id     INT          NOT NULL DEFAULT 0,
  sector_id       INT          NOT NULL DEFAULT 0,
  indice          DECIMAL(5,2) NOT NULL,
  actualizado_por INT          NULL,
  actualizado_at  DATETIME     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_compromiso (empresa_id, anio, sucursal_id, sector_id),
  KEY idx_compromiso_anio (empresa_id, anio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def migrate_cursor(cursor):
    cursor.execute(TABLA)


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
