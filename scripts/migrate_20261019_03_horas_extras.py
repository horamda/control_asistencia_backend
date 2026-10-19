"""Gestion de jornada laboral, etapa C: horas extras (autorizacion en dos pasos) y cierre de periodo mensual.

- jl_reglas: tres campos nuevos (recargo en dias habiles, recargo de descanso y desde que hora del sabado corre).
  La regla de carga inicial de Fuera de convenio (LCT) recibe los valores de la ley (50 %, 100 %, sabado desde 13).
- jl_horas_extra: la decision sobre el excedente de un empleado en un dia (visto bueno del jefe, aprobada, rechazada,
  liquidada). Sin fila = pendiente: los pendientes salen en vivo del calculo.
- jl_horas_extra_eventos: cada paso (quien, cuando, minutos, motivo). Solo se inserta: nunca se edita ni se borra.
- jl_periodos: cierre mensual por empresa, con el calculo registrado al cerrar y la reapertura (motivo y usuario).

No toca ninguna tabla existente fuera del modulo. Reversion: DROP de las tres tablas, DROP de las tres columnas de
jl_reglas y DELETE de la version 20261019_horas_extras en app_schema_versions."""


def _values(row):
    return list(row.values()) if isinstance(row, dict) else list(row)


def _has_column(cursor, table, column):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND COLUMN_NAME = %s", (table, column))
    return int(_values(cursor.fetchone())[0]) > 0


COLUMNAS = (
    ("recargo_habil_pct", "SMALLINT NULL"),
    ("recargo_descanso_pct", "SMALLINT NULL"),
    ("sabado_descanso_desde", "TIME NULL"),
)

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS jl_horas_extra (
      id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id         INT          NOT NULL,
      empleado_id        INT          NOT NULL,
      fecha              DATE         NOT NULL,
      estado             VARCHAR(20)  NOT NULL,
      minutos_excedente  INT          NOT NULL DEFAULT 0,
      propuesta_habil    INT          NOT NULL DEFAULT 0,
      propuesta_descanso INT          NOT NULL DEFAULT 0,
      minutos_habil      INT          NOT NULL DEFAULT 0,
      minutos_descanso   INT          NOT NULL DEFAULT 0,
      recargo_habil      SMALLINT     NULL,
      recargo_descanso   SMALLINT     NULL,
      supera_tope        TINYINT      NOT NULL DEFAULT 0,
      marcas_huella      CHAR(16)     NOT NULL,
      motivo             VARCHAR(255) NULL,
      jefe_por           INT          NULL,
      jefe_at            DATETIME     NULL,
      resuelto_por       INT          NULL,
      resuelto_at        DATETIME     NULL,
      periodo_id         INT UNSIGNED NULL,
      creado_at          DATETIME     NOT NULL,
      actualizado_at     DATETIME     NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_jl_horas_extra (empleado_id, fecha),
      KEY idx_jl_horas_extra_empresa (empresa_id, fecha, estado),
      KEY idx_jl_horas_extra_periodo (periodo_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS jl_horas_extra_eventos (
      id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
      horas_extra_id    INT UNSIGNED NOT NULL,
      empresa_id        INT          NOT NULL,
      accion            VARCHAR(30)  NOT NULL,
      estado_anterior   VARCHAR(20)  NULL,
      estado_nuevo      VARCHAR(20)  NOT NULL,
      minutos_habil     INT          NOT NULL DEFAULT 0,
      minutos_descanso  INT          NOT NULL DEFAULT 0,
      supera_tope       TINYINT      NOT NULL DEFAULT 0,
      motivo            VARCHAR(255) NULL,
      usuario_id        INT          NULL,
      creado_at         DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_jl_he_eventos (horas_extra_id, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS jl_periodos (
      id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id        INT          NOT NULL,
      mes               DATE         NOT NULL,
      estado            VARCHAR(20)  NOT NULL,
      calculo_id        INT UNSIGNED NULL,
      cerrado_por       INT          NULL,
      cerrado_at        DATETIME     NULL,
      reabierto_por     INT          NULL,
      reabierto_at      DATETIME     NULL,
      motivo_reapertura VARCHAR(255) NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_jl_periodos (empresa_id, mes)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def migrate_cursor(cursor):
    for columna, tipo in COLUMNAS:
        if not _has_column(cursor, "jl_reglas", columna):
            cursor.execute(f"ALTER TABLE jl_reglas ADD COLUMN {columna} {tipo}")
    # Solo la version de carga inicial de la LCT (sin usuario) y solo si nadie cargo esos valores.
    cursor.execute("""UPDATE jl_reglas r JOIN jl_convenios c ON c.id = r.convenio_id
                      SET r.recargo_habil_pct = 50, r.recargo_descanso_pct = 100, r.sabado_descanso_desde = '13:00:00'
                      WHERE r.alcance = 'convenio' AND c.codigo = 'LCT' AND r.creado_por IS NULL
                        AND r.recargo_habil_pct IS NULL AND r.recargo_descanso_pct IS NULL AND r.sabado_descanso_desde IS NULL""")
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
