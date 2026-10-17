"""Reglas de avisos por empresa, horario de silencio, envios diferidos/agrupados y comunicados programados."""

from scripts.migrate_20261016_02_reuniones_sucursales import _has_column, _has_index, _values


def _has_table(cursor, table):
    cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                   (table,))
    return int(_values(cursor.fetchone())[0]) > 0

TABLES = (
    # Una fila por empresa y regla solo si se cambio algo: lo que falta usa los valores por defecto del catalogo
    # (services/push_reglas_service.py).
    """
    CREATE TABLE IF NOT EXISTS push_reglas (
      empresa_id      INT          NOT NULL,
      clave           VARCHAR(40)  NOT NULL,
      activo          TINYINT      NOT NULL DEFAULT 1,
      destinatarios   VARCHAR(120) NULL,
      momento         VARCHAR(12)  NOT NULL DEFAULT 'inmediato',
      horarios        VARCHAR(60)  NULL,
      dias            VARCHAR(20)  NULL,
      parametro       INT          NULL,
      actualizado_at  DATETIME     NOT NULL,
      actualizado_por INT          NULL,
      PRIMARY KEY (empresa_id, clave)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS push_config (
      empresa_id      INT      NOT NULL,
      silencio_desde  TIME     NULL,
      silencio_hasta  TIME     NULL,
      actualizado_at  DATETIME NOT NULL,
      actualizado_por INT      NULL,
      PRIMARY KEY (empresa_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS comunicados_programados (
      id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id     INT          NOT NULL,
      titulo         VARCHAR(120) NOT NULL,
      mensaje        TEXT         NOT NULL,
      imagen         MEDIUMBLOB   NULL,
      imagen_push    MEDIUMBLOB   NULL,
      destinatarios  TEXT         NOT NULL,
      alcance        VARCHAR(500) NOT NULL,
      frecuencia     VARCHAR(10)  NOT NULL,
      hora           TIME         NOT NULL,
      fecha_inicio   DATE         NOT NULL,
      fecha_fin      DATE         NULL,
      dias_semana    VARCHAR(20)  NULL,
      dia_mes        TINYINT      NULL,
      solo_habiles   TINYINT      NOT NULL DEFAULT 0,
      max_envios     INT          NULL,
      envios         INT          NOT NULL DEFAULT 0,
      proximo_envio  DATETIME     NULL,
      ultimo_envio   DATETIME     NULL,
      estado         VARCHAR(12)  NOT NULL DEFAULT 'activo',
      creado_por     INT          NULL,
      creado_at      DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_comunicados_programados_proximo (estado, proximo_envio),
      KEY idx_comunicados_programados_empresa (empresa_id, estado)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def migrate_cursor(cursor):
    for sql in TABLES:
        cursor.execute(sql)
    # Envios diferidos (horario de silencio, resumen a una hora) y agrupados en un solo aviso (lote).
    if not _has_column(cursor, "push_envios", "programado_para"):
        cursor.execute("ALTER TABLE push_envios ADD COLUMN programado_para DATETIME NULL AFTER creado_at")
    if not _has_column(cursor, "push_envios", "lote"):
        cursor.execute("ALTER TABLE push_envios ADD COLUMN lote VARCHAR(80) NULL AFTER programado_para")
    if not _has_index(cursor, "push_envios", "idx_push_envios_programado"):
        cursor.execute("ALTER TABLE push_envios ADD KEY idx_push_envios_programado (estado, programado_para)")
    # Un comunicado nacido de una programacion recuerda cual (para listar sus envios).
    if _has_table(cursor, "comunicados") and not _has_column(cursor, "comunicados", "programado_id"):
        cursor.execute("ALTER TABLE comunicados ADD COLUMN programado_id INT UNSIGNED NULL AFTER creado_por")


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
