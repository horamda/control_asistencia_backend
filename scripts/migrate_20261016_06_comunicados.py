"""Comunicados del panel a los empleados (push + bandeja en la app) y quien los leyo."""

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS comunicados (
      id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id     INT          NOT NULL,
      titulo         VARCHAR(120) NOT NULL,
      mensaje        TEXT         NOT NULL,
      alcance        VARCHAR(500) NOT NULL,
      destinatarios  INT          NOT NULL DEFAULT 0,
      creado_por     INT          NULL,
      creado_at      DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_comunicados_empresa (empresa_id, creado_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS comunicado_destinatarios (
      comunicado_id INT UNSIGNED NOT NULL,
      empleado_id   INT          NOT NULL,
      leido_at      DATETIME     NULL,
      PRIMARY KEY (comunicado_id, empleado_id),
      KEY idx_comunicado_destinatarios_empleado (empleado_id, comunicado_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def migrate_cursor(cursor):
    for sql in TABLES:
        cursor.execute(sql)


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
