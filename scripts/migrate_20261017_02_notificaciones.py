"""Bandeja de notificaciones del empleado (services/notificaciones_service.py).

Transicion: crea la tabla y copia los comunicados ya enviados con su lectura (comunicado_destinatarios.leido_at),
para que la campana arranque con lo que el empleado ya tenia en Comunicados. No importa tramites historicos
(adelantos, viaticos, feedback...) ni envia push: solo los eventos nuevos generan notificaciones. Idempotente
(clave unica por empleado y evento); se puede correr varias veces.

Reversion: la tabla es nueva y nada mas depende de ella para funcionar. DROP TABLE empleado_notificaciones y
borrar la version 20261017_notificaciones de app_schema_versions (los comunicados y sus lecturas no se tocan)."""

TABLE = """
    CREATE TABLE IF NOT EXISTS empleado_notificaciones (
      id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id       INT          NOT NULL,
      empleado_id      INT          NOT NULL,
      tipo             VARCHAR(30)  NOT NULL,
      modulo           VARCHAR(40)  NOT NULL,
      titulo           VARCHAR(120) NOT NULL,
      mensaje          VARCHAR(500) NOT NULL,
      referencia_tipo  VARCHAR(40)  NULL,
      referencia_id    BIGINT       NULL,
      ruta             VARCHAR(200) NULL,
      datos            TEXT         NULL,
      clave            VARCHAR(150) NOT NULL,
      creado_at        DATETIME     NOT NULL,
      leido_at         DATETIME     NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_empleado_notificaciones_clave (empleado_id, clave),
      KEY idx_empleado_notificaciones_bandeja (empleado_id, empresa_id, id),
      KEY idx_empleado_notificaciones_no_leidas (empleado_id, leido_at),
      KEY idx_empleado_notificaciones_referencia (referencia_tipo, referencia_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Mismo texto que el push del comunicado (hasta 180 caracteres); el completo sigue en GET /comunicados/{id}.
BACKFILL_COMUNICADOS = """
    INSERT IGNORE INTO empleado_notificaciones
      (empresa_id, empleado_id, tipo, modulo, titulo, mensaje, referencia_tipo, referencia_id, ruta, datos, clave,
       creado_at, leido_at)
    SELECT c.empresa_id, d.empleado_id, 'comunicado', 'comunicados', LEFT(c.titulo, 120),
           CASE WHEN CHAR_LENGTH(c.mensaje) <= 180 THEN c.mensaje ELSE CONCAT(LEFT(c.mensaje, 177), '…') END,
           'comunicado', c.id, CONCAT('/comunicados/', c.id), CONCAT('{"comunicado_id": "', c.id, '"}'),
           CONCAT('comunicado:', c.id), c.creado_at, d.leido_at
    FROM comunicado_destinatarios d
    JOIN comunicados c ON c.id = d.comunicado_id
    ORDER BY c.id, d.empleado_id
"""


def migrate_cursor(cursor):
    from scripts.migrate_20261017_01_push_reglas import _has_table

    cursor.execute(TABLE)
    if _has_table(cursor, "comunicados") and _has_table(cursor, "comunicado_destinatarios"):
        cursor.execute(BACKFILL_COMUNICADOS)


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
