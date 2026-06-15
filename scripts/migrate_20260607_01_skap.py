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
        tables = [
            (
                "skap_preguntas",
                """
                CREATE TABLE skap_preguntas (
                    id                   INT AUTO_INCREMENT PRIMARY KEY,
                    sector_id            INT NOT NULL,
                    categoria            ENUM('S','K','A','P') NOT NULL,
                    descripcion          VARCHAR(255) NOT NULL,
                    peso                 DECIMAL(6,2) NOT NULL DEFAULT 1.00,
                    puntaje_esperado     TINYINT NOT NULL DEFAULT 4,
                    requiere_observacion TINYINT(1) NOT NULL DEFAULT 0,
                    requiere_evidencia   TINYINT(1) NOT NULL DEFAULT 0,
                    activo               TINYINT(1) NOT NULL DEFAULT 1,
                    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_skap_preguntas_sector_categoria_desc (sector_id, categoria, descripcion),
                    INDEX idx_skap_preguntas_sector_activo (sector_id, activo),
                    INDEX idx_skap_preguntas_categoria (categoria),
                    INDEX idx_skap_preguntas_activo (activo),
                    CONSTRAINT fk_skap_preguntas_sector
                        FOREIGN KEY (sector_id) REFERENCES sectores(id) ON DELETE RESTRICT,
                    CONSTRAINT chk_skap_preguntas_puntaje_esperado
                        CHECK (puntaje_esperado BETWEEN 1 AND 5),
                    CONSTRAINT chk_skap_preguntas_peso
                        CHECK (peso > 0)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
            ),
            (
                "skap_evaluaciones",
                """
                CREATE TABLE skap_evaluaciones (
                    id                     INT AUTO_INCREMENT PRIMARY KEY,
                    empresa_id             INT NOT NULL,
                    empleado_id            INT NOT NULL,
                    sector_id              INT NOT NULL,
                    puesto_id              INT NULL,
                    anio                   INT NOT NULL,
                    evaluador_empleado_id   INT NOT NULL,
                    evaluador_usuario_id    INT NULL,
                    fecha_evaluacion       DATE NOT NULL,
                    hora_evaluacion        TIME NOT NULL,
                    promedio_skills        DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                    promedio_knowledge     DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                    promedio_attitude      DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                    promedio_performance   DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                    promedio_general       DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                    nivel                  VARCHAR(40) NOT NULL DEFAULT 'Critico',
                    observaciones_generales TEXT NULL,
                    pdp_generado_at        DATETIME NULL,
                    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_skap_evaluaciones_empleado_anio (empleado_id, anio),
                    INDEX idx_skap_evaluaciones_empresa_anio (empresa_id, anio),
                    INDEX idx_skap_evaluaciones_sector_anio (sector_id, anio),
                    INDEX idx_skap_evaluaciones_evaluador (evaluador_empleado_id),
                    INDEX idx_skap_evaluaciones_promedio (promedio_general),
                    INDEX idx_skap_evaluaciones_created_at (created_at),
                    CONSTRAINT fk_skap_evaluaciones_empleado
                        FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_skap_evaluaciones_sector
                        FOREIGN KEY (sector_id) REFERENCES sectores(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_skap_evaluaciones_puesto
                        FOREIGN KEY (puesto_id) REFERENCES puestos(id) ON DELETE SET NULL,
                    CONSTRAINT fk_skap_evaluaciones_evaluador_empleado
                        FOREIGN KEY (evaluador_empleado_id) REFERENCES empleados(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_skap_evaluaciones_evaluador_usuario
                        FOREIGN KEY (evaluador_usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL,
                    CONSTRAINT chk_skap_evaluaciones_anio
                        CHECK (anio >= 2020 AND anio <= 2100)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
            ),
            (
                "skap_evaluaciones_detalle",
                """
                CREATE TABLE skap_evaluaciones_detalle (
                    id                        INT AUTO_INCREMENT PRIMARY KEY,
                    evaluacion_id             INT NOT NULL,
                    pregunta_id               INT NOT NULL,
                    categoria                 ENUM('S','K','A','P') NOT NULL,
                    descripcion_snapshot      VARCHAR(255) NOT NULL,
                    peso_snapshot             DECIMAL(6,2) NOT NULL DEFAULT 1.00,
                    puntaje_esperado_snapshot TINYINT NOT NULL DEFAULT 4,
                    puntaje_obtenido          TINYINT NOT NULL,
                    observacion               TEXT NULL,
                    evidencia                 TEXT NULL,
                    cumple_esperado           TINYINT(1) NOT NULL DEFAULT 0,
                    created_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_skap_evaluaciones_detalle (evaluacion_id, pregunta_id),
                    INDEX idx_skap_evaluaciones_detalle_eval_categoria (evaluacion_id, categoria),
                    INDEX idx_skap_evaluaciones_detalle_pregunta (pregunta_id),
                    CONSTRAINT fk_skap_detalle_evaluacion
                        FOREIGN KEY (evaluacion_id) REFERENCES skap_evaluaciones(id) ON DELETE CASCADE,
                    CONSTRAINT fk_skap_detalle_pregunta
                        FOREIGN KEY (pregunta_id) REFERENCES skap_preguntas(id) ON DELETE RESTRICT,
                    CONSTRAINT chk_skap_detalle_puntaje
                        CHECK (puntaje_obtenido BETWEEN 1 AND 5)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
            ),
            (
                "skap_planes_desarrollo",
                """
                CREATE TABLE skap_planes_desarrollo (
                    id                INT AUTO_INCREMENT PRIMARY KEY,
                    evaluacion_id     INT NOT NULL,
                    empresa_id        INT NOT NULL,
                    empleado_id       INT NOT NULL,
                    sector_id         INT NOT NULL,
                    puesto_id         INT NULL,
                    anio              INT NOT NULL,
                    promedio_general  DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                    nivel             VARCHAR(40) NOT NULL DEFAULT 'Critico',
                    observaciones     TEXT NULL,
                    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_skap_planes_evaluacion (evaluacion_id),
                    INDEX idx_skap_planes_empleado_anio (empleado_id, anio),
                    INDEX idx_skap_planes_sector_anio (sector_id, anio),
                    INDEX idx_skap_planes_empresa_anio (empresa_id, anio),
                    CONSTRAINT fk_skap_planes_evaluacion
                        FOREIGN KEY (evaluacion_id) REFERENCES skap_evaluaciones(id) ON DELETE CASCADE,
                    CONSTRAINT fk_skap_planes_empleado
                        FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_skap_planes_sector
                        FOREIGN KEY (sector_id) REFERENCES sectores(id) ON DELETE RESTRICT,
                    CONSTRAINT fk_skap_planes_puesto
                        FOREIGN KEY (puesto_id) REFERENCES puestos(id) ON DELETE SET NULL,
                    CONSTRAINT chk_skap_planes_anio
                        CHECK (anio >= 2020 AND anio <= 2100)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
            ),
            (
                "skap_planes_desarrollo_acciones",
                """
                CREATE TABLE skap_planes_desarrollo_acciones (
                    id                      INT AUTO_INCREMENT PRIMARY KEY,
                    plan_id                 INT NOT NULL,
                    categoria               ENUM('S','K','A','P') NULL,
                    accion                  VARCHAR(255) NOT NULL,
                    responsable_empleado_id INT NULL,
                    fecha_compromiso        DATE NULL,
                    estado                  VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                    comentarios             TEXT NULL,
                    completado_at           DATETIME NULL,
                    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_skap_acciones_plan_estado (plan_id, estado),
                    INDEX idx_skap_acciones_responsable (responsable_empleado_id),
                    INDEX idx_skap_acciones_compromiso (fecha_compromiso),
                    CONSTRAINT fk_skap_acciones_plan
                        FOREIGN KEY (plan_id) REFERENCES skap_planes_desarrollo(id) ON DELETE CASCADE,
                    CONSTRAINT fk_skap_acciones_responsable
                        FOREIGN KEY (responsable_empleado_id) REFERENCES empleados(id) ON DELETE SET NULL,
                    CONSTRAINT chk_skap_acciones_estado
                        CHECK (estado IN ('pendiente', 'en_proceso', 'completado', 'cancelado'))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
            ),
        ]

        for table_name, ddl in tables:
            if not _table_exists(cursor, table_name):
                cursor.execute(ddl)
                db.commit()
                print(f"[created] tabla {table_name}")
            else:
                print(f"[skip] tabla {table_name} ya existe")

        print("[done] migration 20260607_01_skap")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
