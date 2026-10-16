"""Notificaciones push (Firebase Cloud Messaging): dispositivos de cada empleado y cola de envios."""

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS push_dispositivos (
      id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id    INT          NOT NULL,
      empleado_id   INT          NOT NULL,
      token         VARCHAR(1024) NOT NULL,
      token_hash    CHAR(64)     NOT NULL,
      plataforma    VARCHAR(10)  NOT NULL,
      app_version   VARCHAR(40)  NULL,
      activo        TINYINT      NOT NULL DEFAULT 1,
      error         VARCHAR(255) NULL,
      creado_at     DATETIME     NOT NULL,
      ultimo_uso_at DATETIME     NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_push_dispositivos_token (token_hash),
      KEY idx_push_dispositivos_empleado (empleado_id, activo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS push_envios (
      id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id   INT          NOT NULL,
      empleado_id  INT          NOT NULL,
      tipo         VARCHAR(30)  NOT NULL,
      clave        VARCHAR(150) NULL,
      titulo       VARCHAR(120) NOT NULL,
      cuerpo       VARCHAR(500) NOT NULL,
      datos        TEXT         NULL,
      estado       VARCHAR(16)  NOT NULL DEFAULT 'pendiente',
      intentos     TINYINT      NOT NULL DEFAULT 0,
      dispositivos TINYINT      NOT NULL DEFAULT 0,
      error        VARCHAR(255) NULL,
      creado_at    DATETIME     NOT NULL,
      enviado_at   DATETIME     NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_push_envios_clave (clave),
      KEY idx_push_envios_estado (estado, creado_at),
      KEY idx_push_envios_empleado (empleado_id, creado_at)
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
