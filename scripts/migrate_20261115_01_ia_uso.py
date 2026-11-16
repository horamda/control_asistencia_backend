"""Registro de uso de inteligencia artificial (generador de trivias y pruebas de conexion).

Una fila por llamada al proveedor: quien, proveedor, modelo, tokens, costo estimado y resultado. No guarda el
contenido enviado ni las preguntas generadas. La configuracion (proveedor, modelo, limites) vive en system_config
con claves ia_*; las claves de API solo en variables de entorno.

Reversion: DROP TABLE ia_uso; DELETE FROM system_config WHERE config_key LIKE 'ia\\_%';
y borrar la version 20261115_ia_uso de app_schema_versions."""

TABLA = """
CREATE TABLE IF NOT EXISTS ia_uso (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  creado_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  usuario_id     INT          NULL,
  proveedor      VARCHAR(20)  NOT NULL,
  modelo         VARCHAR(120) NOT NULL,
  operacion      VARCHAR(20)  NOT NULL,
  estado         VARCHAR(10)  NOT NULL,
  error_tipo     VARCHAR(20)  NULL,
  tokens_entrada INT          NOT NULL DEFAULT 0,
  tokens_salida  INT          NOT NULL DEFAULT 0,
  costo_usd      DECIMAL(10,4) NOT NULL DEFAULT 0,
  duracion_ms    INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_ia_uso_fecha (creado_en)
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
