"""Gestion de jornada laboral, etapa B: calculos registrados de horas (solo resultados; los fichajes no se tocan).

- jl_calculos: cada vez que alguien registra el calculo de un periodo (quien, cuando, periodo, motivo).
- jl_resultados_dia: el resultado por empleado y dia de ese calculo, con las versiones de regla usadas y una huella de
  las marcas. Un recalculo crea filas nuevas: los calculos anteriores se conservan (trazabilidad). El vigente de cada
  dia es el de calculo_id mas alto.

Reversion: DROP de las dos tablas y DELETE de la version 20261019_jornada_calculo en app_schema_versions."""

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS jl_calculos (
      id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id   INT          NOT NULL,
      desde        DATE         NOT NULL,
      hasta        DATE         NOT NULL,
      empleados    INT          NOT NULL DEFAULT 0,
      dias         INT          NOT NULL DEFAULT 0,
      motivo       VARCHAR(255) NULL,
      creado_por   INT          NULL,
      creado_at    DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_jl_calculos_empresa (empresa_id, desde)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS jl_resultados_dia (
      id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      calculo_id           INT UNSIGNED NOT NULL,
      empresa_id           INT          NOT NULL,
      empleado_id          INT          NOT NULL,
      fecha                DATE         NOT NULL,
      estado               VARCHAR(20)  NOT NULL,
      tipo_dia             VARCHAR(20)  NOT NULL,
      minutos_programados  INT          NOT NULL DEFAULT 0,
      minutos_fichados     INT          NOT NULL DEFAULT 0,
      minutos_trabajados   INT          NOT NULL DEFAULT 0,
      minutos_ordinarios   INT          NOT NULL DEFAULT 0,
      minutos_excedente    INT          NOT NULL DEFAULT 0,
      minutos_faltantes    INT          NOT NULL DEFAULT 0,
      minutos_nocturnos    INT          NOT NULL DEFAULT 0,
      minutos_descanso     INT          NOT NULL DEFAULT 0,
      cruza_medianoche     TINYINT      NOT NULL DEFAULT 0,
      reglas               VARCHAR(255) NULL,
      marcas_huella        CHAR(16)     NOT NULL,
      detalle              TEXT         NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_jl_resultados (calculo_id, empleado_id, fecha),
      KEY idx_jl_resultados_empleado (empleado_id, fecha, calculo_id),
      KEY idx_jl_resultados_empresa (empresa_id, fecha)
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
