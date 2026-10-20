"""Correcciones de ubicacion de fichadas: valores anteriores y nuevos de cada marca recalculada.

Cuando una sucursal tenia mal cargadas sus coordenadas, sus fichadas se validaron contra un punto equivocado. La
correccion (panel, Sucursales) recalcula distancia y "dentro del radio" con la ubicacion actual y deja aca lo que
habia antes, quien lo hizo, cuando, el motivo y el evento de seguridad anulado (si lo hubo). Solo se inserta.

Reversion: DROP TABLE asistencia_marcas_geo_correcciones y DELETE de la version 20261020_geo_correcciones en
app_schema_versions (los valores anteriores de cada marca quedan en esta tabla para restaurarlos si hiciera falta)."""

TABLA = """
CREATE TABLE IF NOT EXISTS asistencia_marcas_geo_correcciones (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  lote                 CHAR(32)     NOT NULL,
  marca_id             BIGINT       NOT NULL,
  empresa_id           INT          NOT NULL,
  sucursal_id          INT          NOT NULL,
  antes_gps_ok         TINYINT      NULL,
  antes_distancia_m    DECIMAL(10,2) NULL,
  antes_tolerancia_m   DECIMAL(10,2) NULL,
  antes_ref_lat        DECIMAL(10,7) NULL,
  antes_ref_lon        DECIMAL(10,7) NULL,
  despues_gps_ok       TINYINT      NOT NULL,
  despues_distancia_m  DECIMAL(10,2) NOT NULL,
  despues_tolerancia_m DECIMAL(10,2) NOT NULL,
  despues_ref_lat      DECIMAL(10,7) NOT NULL,
  despues_ref_lon      DECIMAL(10,7) NOT NULL,
  evento_anulado_id    BIGINT       NULL,
  motivo               VARCHAR(255) NOT NULL,
  usuario_id           INT          NULL,
  creado_at            DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY idx_geo_corr_marca (marca_id),
  KEY idx_geo_corr_lote (lote),
  KEY idx_geo_corr_sucursal (sucursal_id, creado_at)
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
