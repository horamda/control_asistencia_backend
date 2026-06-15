import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
        (table_name,),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _table_exists(cursor, "feedback_motivos"):
            cursor.execute(
                """
                CREATE TABLE feedback_motivos (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    nombre        VARCHAR(120) NOT NULL,
                    descripcion   TEXT NULL,
                    sla_dias      INT NOT NULL DEFAULT 1,
                    activo        TINYINT(1) NOT NULL DEFAULT 1,
                    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_feedback_motivo_nombre (nombre),
                    INDEX idx_feedback_motivo_activo (activo),
                    INDEX idx_feedback_motivo_nombre (nombre)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            db.commit()
            print("[created] tabla feedback_motivos")
        else:
            print("[skip] tabla feedback_motivos ya existe")

        if not _table_exists(cursor, "feedback_clientes"):
            cursor.execute(
                """
                CREATE TABLE feedback_clientes (
                    id                           INT AUTO_INCREMENT PRIMARY KEY,
                    sucursal_origen              INT NULL,
                    codigo_externo               VARCHAR(50) NOT NULL,
                    razon_social                 VARCHAR(255) NOT NULL,
                    nombre_fantasia              VARCHAR(255) NULL,
                    telefonos                    VARCHAR(120) NULL,
                    movil                        VARCHAR(120) NULL,
                    email                        VARCHAR(255) NULL,
                    domicilio                    VARCHAR(255) NULL,
                    localidad                    VARCHAR(120) NULL,
                    descripcion_localidad        VARCHAR(255) NULL,
                    provincia                    VARCHAR(120) NULL,
                    descripcion_provincia        VARCHAR(255) NULL,
                    tipo_codigo                  VARCHAR(50) NULL,
                    tipo_descripcion             VARCHAR(255) NULL,
                    comentario                   TEXT NULL,
                    latitud                      DECIMAL(10,6) NULL,
                    longitud                     DECIMAL(10,6) NULL,
                    activo                       TINYINT(1) NOT NULL DEFAULT 1,
                    created_at                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_feedback_cliente_sucursal_codigo (sucursal_origen, codigo_externo),
                    INDEX idx_feedback_cliente_razon_social (razon_social),
                    INDEX idx_feedback_cliente_nombre_fantasia (nombre_fantasia),
                    INDEX idx_feedback_cliente_tipo (tipo_descripcion),
                    INDEX idx_feedback_cliente_localidad (localidad),
                    INDEX idx_feedback_cliente_activo (activo)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            db.commit()
            print("[created] tabla feedback_clientes")
        else:
            print("[skip] tabla feedback_clientes ya existe")

        if not _table_exists(cursor, "feedbacks"):
            cursor.execute(
                """
                CREATE TABLE feedbacks (
                    id                               INT AUTO_INCREMENT PRIMARY KEY,
                    empresa_id                       INT NOT NULL,
                    empleado_id                      INT NOT NULL,
                    jefe_directo_id                  INT NOT NULL,
                    cliente_id                       INT NOT NULL,
                    motivo_id                        INT NOT NULL,
                    descripcion                      TEXT NOT NULL,
                    estado                           VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                    fecha_vencimiento                DATE NOT NULL,
                    cliente_codigo_snapshot          VARCHAR(50) NULL,
                    cliente_razon_social_snapshot    VARCHAR(255) NULL,
                    cliente_nombre_fantasia_snapshot VARCHAR(255) NULL,
                    cliente_tipo_snapshot            VARCHAR(255) NULL,
                    motivo_nombre_snapshot           VARCHAR(120) NULL,
                    jefe_directo_nombre_snapshot     VARCHAR(255) NULL,
                    created_at                       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at                       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    resuelto_at                      DATETIME NULL,
                    resuelto_por_empleado_id         INT NULL,
                    resolucion_descripcion           TEXT NULL,
                    resuelto_en_sla                  TINYINT(1) NULL,
                    INDEX idx_feedbacks_empresa (empresa_id),
                    INDEX idx_feedbacks_empleado (empleado_id),
                    INDEX idx_feedbacks_jefe_directo (jefe_directo_id),
                    INDEX idx_feedbacks_cliente (cliente_id),
                    INDEX idx_feedbacks_motivo (motivo_id),
                    INDEX idx_feedbacks_estado (estado),
                    INDEX idx_feedbacks_created_at (created_at),
                    INDEX idx_feedbacks_vencimiento (fecha_vencimiento),
                    INDEX idx_feedbacks_resuelto_at (resuelto_at),
                    CONSTRAINT fk_feedbacks_empleado FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_feedbacks_jefe_directo FOREIGN KEY (jefe_directo_id) REFERENCES empleados(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_feedbacks_cliente FOREIGN KEY (cliente_id) REFERENCES feedback_clientes(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_feedbacks_motivo FOREIGN KEY (motivo_id) REFERENCES feedback_motivos(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_feedbacks_resuelto_por FOREIGN KEY (resuelto_por_empleado_id) REFERENCES empleados(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            db.commit()
            print("[created] tabla feedbacks")
        else:
            print("[skip] tabla feedbacks ya existe")

        print("[done] migration 20260606_01_feedback")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
