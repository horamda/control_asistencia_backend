"""Gestion de jornada laboral, etapa A: convenios, reglas con vigencia y asignacion de convenio a empleados.

Tablas nuevas y complementarias (no se modifica ninguna existente ni se tocan los fichajes):
- jl_convenios: convenios y acuerdos de cada empresa.
- jl_reglas: reglas de jornada por nivel (empresa, sucursal, convenio, empleado) con vigencia. Nunca se editan: una
  version nueva cierra la anterior (vigente_hasta) y la referencia (reemplaza_id). Un campo NULL hereda del nivel
  superior.
- jl_asignaciones: convenio de cada empleado con vigencia e historial (mismo esquema de versiones).

Carga inicial por empresa (idempotente): "Fuera de convenio (LCT)" con valores legales de referencia (Ley 11.544,
jornada nocturna, Decreto 484/2000) y "Camioneros (CCT 40/89)" y "SUTIAGA" sin valores, para que RR. HH. los complete.
Reversion: DROP de las tres tablas y DELETE de la version 20261019_jornada_laboral en app_schema_versions."""

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS jl_convenios (
      id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id    INT          NOT NULL,
      codigo        VARCHAR(40)  NOT NULL,
      nombre        VARCHAR(120) NOT NULL,
      tipo          VARCHAR(20)  NOT NULL DEFAULT 'cct',
      descripcion   VARCHAR(500) NULL,
      activo        TINYINT      NOT NULL DEFAULT 1,
      creado_por    INT          NULL,
      creado_at     DATETIME     NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_jl_convenios_codigo (empresa_id, codigo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS jl_reglas (
      id                        INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id                INT          NOT NULL,
      alcance                   VARCHAR(20)  NOT NULL,
      sucursal_id               INT          NULL,
      convenio_id               INT UNSIGNED NULL,
      empleado_id               INT          NULL,
      vigente_desde             DATE         NOT NULL,
      vigente_hasta             DATE         NULL,
      horas_semanales           DECIMAL(5,2) NULL,
      horas_diarias             DECIMAL(4,2) NULL,
      dias_laborales            VARCHAR(20)  NULL,
      regimen_distribucion      VARCHAR(20)  NULL,
      descanso_computable_min   SMALLINT     NULL,
      tolerancia_ingreso_min    SMALLINT     NULL,
      tolerancia_salida_min     SMALLINT     NULL,
      nocturna_desde            TIME         NULL,
      nocturna_hasta            TIME         NULL,
      horas_nocturnas_diarias   DECIMAL(4,2) NULL,
      trabaja_feriados          TINYINT      NULL,
      tope_extras_mes           SMALLINT     NULL,
      tope_extras_anio          SMALLINT     NULL,
      banco_horas_habilitado    TINYINT      NULL,
      observaciones             VARCHAR(255) NULL,
      motivo                    VARCHAR(255) NULL,
      reemplaza_id              INT UNSIGNED NULL,
      creado_por                INT          NULL,
      creado_at                 DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_jl_reglas_alcance (empresa_id, alcance, vigente_desde),
      KEY idx_jl_reglas_empleado (empleado_id, vigente_desde),
      KEY idx_jl_reglas_convenio (convenio_id, vigente_desde),
      KEY idx_jl_reglas_sucursal (sucursal_id, vigente_desde)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS jl_asignaciones (
      id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id     INT          NOT NULL,
      empleado_id    INT          NOT NULL,
      convenio_id    INT UNSIGNED NOT NULL,
      vigente_desde  DATE         NOT NULL,
      vigente_hasta  DATE         NULL,
      motivo         VARCHAR(255) NULL,
      reemplaza_id   INT UNSIGNED NULL,
      creado_por     INT          NULL,
      creado_at      DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_jl_asignaciones_empleado (empleado_id, vigente_desde),
      KEY idx_jl_asignaciones_convenio (convenio_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

CONVENIOS_BASE = (
    ("LCT", "Fuera de convenio (LCT)", "ley",
     "Ley de Contrato de Trabajo y Ley 11.544. Valores de referencia: verificarlos con el asesor laboral."),
    ("CCT_40_89", "Camioneros (CCT 40/89)", "cct", "Completar jornada, nocturnidad y topes según el convenio vigente."),
    ("SUTIAGA", "SUTIAGA", "cct", "Completar jornada, nocturnidad y topes según el convenio vigente."),
)


def migrate_cursor(cursor):
    for sql in TABLES:
        cursor.execute(sql)
    for codigo, nombre, tipo, descripcion in CONVENIOS_BASE:
        cursor.execute(
            """INSERT INTO jl_convenios (empresa_id, codigo, nombre, tipo, descripcion, activo, creado_at)
               SELECT e.id, %s, %s, %s, %s, 1, NOW() FROM empresas e
               WHERE NOT EXISTS (SELECT 1 FROM jl_convenios c WHERE c.empresa_id = e.id AND c.codigo = %s)""",
            (codigo, nombre, tipo, descripcion, codigo))
    # Reglas de referencia del regimen general (editables: una version nueva las reemplaza).
    cursor.execute(
        """INSERT INTO jl_reglas (empresa_id, alcance, convenio_id, vigente_desde, horas_semanales, horas_diarias,
                                  nocturna_desde, nocturna_hasta, horas_nocturnas_diarias, tope_extras_mes,
                                  tope_extras_anio, observaciones, motivo, creado_at)
           SELECT c.empresa_id, 'convenio', c.id, '2000-01-01', 48, 8, '21:00:00', '06:00:00', 7, 30, 200,
                  'Ley 11.544 (8 h diarias, 48 semanales), jornada nocturna de 21 a 6 (7 h) y Decreto 484/2000 (30 h extras por mes, 200 por año). Verificar con el asesor laboral.',
                  'Carga inicial', NOW()
           FROM jl_convenios c
           WHERE c.codigo = 'LCT' AND NOT EXISTS (SELECT 1 FROM jl_reglas r WHERE r.convenio_id = c.id)""")


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
