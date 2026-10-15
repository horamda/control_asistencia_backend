"""Modulo Reuniones: definiciones recurrentes, convocados, ocurrencias y asistencia por QR."""

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS reuniones (
      id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id          INT          NOT NULL,
      nombre              VARCHAR(150) NOT NULL,
      descripcion         TEXT         NULL,
      lugar               VARCHAR(150) NULL,
      frecuencia          VARCHAR(10)  NOT NULL,
      dias_semana         VARCHAR(20)  NULL,
      mensual_tipo        VARCHAR(10)  NULL,
      dia_mes             TINYINT      NULL,
      semana_mes          TINYINT      NULL,
      hora_inicio         TIME         NOT NULL,
      duracion_min        SMALLINT     NOT NULL DEFAULT 60,
      fecha_inicio        DATE         NOT NULL,
      fecha_fin           DATE         NULL,
      tolerancia_antes_min SMALLINT    NOT NULL DEFAULT 15,
      tarde_despues_min   SMALLINT     NOT NULL DEFAULT 10,
      cierre_despues_min  SMALLINT     NULL,
      qr_modo             VARCHAR(10)  NOT NULL DEFAULT 'fijo',
      qr_version          INT          NOT NULL DEFAULT 1,
      activa              TINYINT      NOT NULL DEFAULT 1,
      creado_por          INT          NULL,
      created_at          DATETIME     NOT NULL,
      updated_at          DATETIME     NOT NULL,
      PRIMARY KEY (id),
      KEY idx_reuniones_empresa (empresa_id, activa)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS reunion_participantes (
      id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
      reunion_id  INT UNSIGNED NOT NULL,
      empleado_id INT          NULL,
      sector_id   INT          NULL,
      puesto_id   INT          NULL,
      PRIMARY KEY (id),
      KEY idx_reunion_participantes_reunion (reunion_id),
      KEY idx_reunion_participantes_empleado (empleado_id),
      CONSTRAINT fk_reunion_participantes_reunion FOREIGN KEY (reunion_id) REFERENCES reuniones (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS reunion_ocurrencias (
      id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id         INT          NOT NULL,
      reunion_id         INT UNSIGNED NOT NULL,
      fecha              DATE         NOT NULL,
      inicio             DATETIME     NOT NULL,
      fin                DATETIME     NOT NULL,
      ventana_desde      DATETIME     NOT NULL,
      ventana_hasta      DATETIME     NOT NULL,
      tarde_desde        DATETIME     NOT NULL,
      estado             VARCHAR(12)  NOT NULL DEFAULT 'programada',
      motivo_cancelacion VARCHAR(255) NULL,
      convocados         INT          NULL,
      cerrada_at         DATETIME     NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_reunion_ocurrencias_fecha (reunion_id, fecha),
      KEY idx_reunion_ocurrencias_empresa_fecha (empresa_id, fecha),
      CONSTRAINT fk_reunion_ocurrencias_reunion FOREIGN KEY (reunion_id) REFERENCES reuniones (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS reunion_asistencias (
      id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
      empresa_id    INT          NOT NULL,
      reunion_id    INT UNSIGNED NOT NULL,
      ocurrencia_id INT UNSIGNED NOT NULL,
      empleado_id   INT          NOT NULL,
      fecha         DATE         NOT NULL,
      estado        VARCHAR(12)  NOT NULL,
      registrado_at DATETIME     NULL,
      metodo        VARCHAR(12)  NULL,
      lat           DECIMAL(10,7) NULL,
      lon           DECIMAL(10,7) NULL,
      usuario_id    INT          NULL,
      observaciones VARCHAR(255) NULL,
      updated_at    DATETIME     NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_reunion_asistencias_empleado (ocurrencia_id, empleado_id),
      KEY idx_reunion_asistencias_empleado_fecha (empleado_id, fecha),
      KEY idx_reunion_asistencias_reunion_fecha (reunion_id, fecha),
      CONSTRAINT fk_reunion_asistencias_ocurrencia FOREIGN KEY (ocurrencia_id) REFERENCES reunion_ocurrencias (id) ON DELETE CASCADE
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
