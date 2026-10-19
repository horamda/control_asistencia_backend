"""Gestion de jornada laboral, etapa D: banco de horas.

- jl_banco_acuerdos: acuerdo de banco de horas de cada empleado, con vigencia y versiones (nunca se reescribe: una
  version nueva cierra la anterior). Fija los factores de equivalencia (hora habil y de descanso), el saldo maximo y
  en cuantos meses vencen las horas acreditadas.
- jl_banco_movimientos: libro de movimientos en minutos (credito +, debito -). Solo se inserta: un error se corrige
  con una reversion (otro movimiento que referencia al original; cada uno se revierte una sola vez).
- jl_horas_extra.destino: 'pago' o 'banco' (lo decide RR. HH. al aprobar). Al cerrar el mes, lo aprobado al banco
  pasa a 'compensada' y se acredita.

No toca ninguna tabla existente fuera del modulo. Reversion: DROP de las dos tablas, DROP de la columna destino y
DELETE de la version 20261019_banco_horas en app_schema_versions."""


def _values(row):
    return list(row.values()) if isinstance(row, dict) else list(row)


def _has_column(cursor, table, column):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND COLUMN_NAME = %s", (table, column))
    return int(_values(cursor.fetchone())[0]) > 0


TABLES = (
    """
    CREATE TABLE IF NOT EXISTS jl_banco_acuerdos (
      id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id       INT          NOT NULL,
      empleado_id      INT          NOT NULL,
      vigente_desde    DATE         NOT NULL,
      vigente_hasta    DATE         NULL,
      factor_habil     DECIMAL(4,2) NOT NULL,
      factor_descanso  DECIMAL(4,2) NOT NULL,
      saldo_maximo_min INT          NULL,
      vence_meses      SMALLINT     NULL,
      motivo           VARCHAR(255) NULL,
      reemplaza_id     INT UNSIGNED NULL,
      creado_por       INT          NULL,
      creado_at        DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_jl_banco_acuerdos (empleado_id, vigente_desde),
      KEY idx_jl_banco_acuerdos_empresa (empresa_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS jl_banco_movimientos (
      id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id      INT          NOT NULL,
      empleado_id     INT          NOT NULL,
      fecha           DATE         NOT NULL,
      tipo            VARCHAR(20)  NOT NULL,
      minutos         INT          NOT NULL,
      vence           DATE         NULL,
      horas_extra_id  INT UNSIGNED NULL,
      periodo_id      INT UNSIGNED NULL,
      revierte_id     INT UNSIGNED NULL,
      motivo          VARCHAR(255) NULL,
      creado_por      INT          NULL,
      creado_at       DATETIME     NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_jl_banco_revierte (revierte_id),
      KEY idx_jl_banco_mov_empleado (empleado_id, fecha, id),
      KEY idx_jl_banco_mov_empresa (empresa_id, fecha),
      KEY idx_jl_banco_mov_periodo (periodo_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def migrate_cursor(cursor):
    for sql in TABLES:
        cursor.execute(sql)
    if not _has_column(cursor, "jl_horas_extra", "destino"):
        cursor.execute("ALTER TABLE jl_horas_extra ADD COLUMN destino VARCHAR(10) NOT NULL DEFAULT 'pago'")


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
