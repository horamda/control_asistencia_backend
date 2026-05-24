import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1
        """,
        (table_name,),
    )
    return cursor.fetchone() is not None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        if not _table_exists(cursor, "trivias"):
            cursor.execute("""
                CREATE TABLE trivias (
                    id               INT AUTO_INCREMENT PRIMARY KEY,
                    titulo           VARCHAR(200) NOT NULL,
                    descripcion      TEXT,
                    fecha_inicio     DATETIME NOT NULL,
                    fecha_fin        DATETIME NOT NULL,
                    estado           ENUM('programada','activa','finalizada','inactiva') NOT NULL DEFAULT 'programada',
                    premio           VARCHAR(300),
                    mensaje_ganador  TEXT,
                    sector_id        INT NULL,
                    anio             INT NOT NULL,
                    creado_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_trivias_estado   (estado),
                    INDEX idx_trivias_anio     (anio),
                    INDEX idx_trivias_fechas   (fecha_inicio, fecha_fin)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivias")
        else:
            print("[skip] tabla trivias ya existe")

        if not _table_exists(cursor, "trivia_preguntas"):
            cursor.execute("""
                CREATE TABLE trivia_preguntas (
                    id                  INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id           INT NOT NULL,
                    texto               VARCHAR(600) NOT NULL,
                    opcion_a            VARCHAR(300) NOT NULL,
                    opcion_b            VARCHAR(300) NOT NULL,
                    opcion_c            VARCHAR(300) NOT NULL,
                    opcion_d            VARCHAR(300) NOT NULL,
                    respuesta_correcta  ENUM('A','B','C','D') NOT NULL,
                    puntos              INT NOT NULL DEFAULT 10,
                    activa              TINYINT(1) NOT NULL DEFAULT 1,
                    orden               INT NOT NULL DEFAULT 0,
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id) ON DELETE CASCADE,
                    INDEX idx_tp_trivia_activa (trivia_id, activa, orden)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_preguntas")
        else:
            print("[skip] tabla trivia_preguntas ya existe")

        if not _table_exists(cursor, "trivia_resultados"):
            cursor.execute("""
                CREATE TABLE trivia_resultados (
                    id                          INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id                   INT NOT NULL,
                    empleado_id                 INT NOT NULL,
                    empleado_dni                VARCHAR(20) NOT NULL,
                    fecha_inicio_participacion  DATETIME NOT NULL,
                    fecha_finalizacion          DATETIME NULL,
                    tiempo_total_segundos       INT NULL,
                    puntos_total                INT NOT NULL DEFAULT 0,
                    correctas                   INT NOT NULL DEFAULT 0,
                    incorrectas                 INT NOT NULL DEFAULT 0,
                    posicion                    INT NULL,
                    es_ganador                  TINYINT(1) NOT NULL DEFAULT 0,
                    estado_resultado            ENUM('en_progreso','completado') NOT NULL DEFAULT 'en_progreso',
                    UNIQUE KEY uq_tr_trivia_empleado (trivia_id, empleado_id),
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id),
                    INDEX idx_tr_trivia_ranking (trivia_id, puntos_total, tiempo_total_segundos, fecha_inicio_participacion)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_resultados")
        else:
            print("[skip] tabla trivia_resultados ya existe")

        if not _table_exists(cursor, "trivia_respuestas"):
            cursor.execute("""
                CREATE TABLE trivia_respuestas (
                    id                        INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id                 INT NOT NULL,
                    pregunta_id               INT NOT NULL,
                    empleado_id               INT NOT NULL,
                    empleado_dni              VARCHAR(20) NOT NULL,
                    respuesta_seleccionada    ENUM('A','B','C','D') NOT NULL,
                    correcta                  TINYINT(1) NOT NULL DEFAULT 0,
                    puntos_obtenidos          INT NOT NULL DEFAULT 0,
                    tiempo_respuesta_segundos INT NULL,
                    fecha_respuesta           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id),
                    FOREIGN KEY (pregunta_id) REFERENCES trivia_preguntas(id),
                    INDEX idx_tresp_trivia_emp (trivia_id, empleado_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_respuestas")
        else:
            print("[skip] tabla trivia_respuestas ya existe")

        if not _table_exists(cursor, "trivia_ganadores"):
            cursor.execute("""
                CREATE TABLE trivia_ganadores (
                    id                    INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id             INT NOT NULL,
                    empleado_id           INT NOT NULL,
                    empleado_dni          VARCHAR(20) NOT NULL,
                    empleado_nombre       VARCHAR(200),
                    puntos_total          INT,
                    tiempo_total_segundos INT,
                    posicion              INT NOT NULL DEFAULT 1,
                    fecha_registro        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_tg_trivia (trivia_id),
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_ganadores")
        else:
            print("[skip] tabla trivia_ganadores ya existe")

        if not _table_exists(cursor, "trivia_notificaciones"):
            cursor.execute("""
                CREATE TABLE trivia_notificaciones (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    trivia_id    INT NOT NULL,
                    empleado_id  INT NOT NULL,
                    empleado_dni VARCHAR(20) NOT NULL,
                    tipo         ENUM('recordatorio_24h','recordatorio_2h') NOT NULL,
                    mensaje      TEXT,
                    leida        TINYINT(1) NOT NULL DEFAULT 0,
                    enviada_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_tn_notif (trivia_id, empleado_id, tipo),
                    FOREIGN KEY (trivia_id) REFERENCES trivias(id),
                    INDEX idx_tn_emp_leida (empleado_id, leida)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_notificaciones")
        else:
            print("[skip] tabla trivia_notificaciones ya existe")

        if not _table_exists(cursor, "trivia_ranking_anual"):
            cursor.execute("""
                CREATE TABLE trivia_ranking_anual (
                    id                   INT AUTO_INCREMENT PRIMARY KEY,
                    anio                 INT NOT NULL,
                    empleado_id          INT NOT NULL,
                    empleado_dni         VARCHAR(20) NOT NULL,
                    empleado_nombre      VARCHAR(200),
                    puntos_anuales       INT NOT NULL DEFAULT 0,
                    trivias_participadas INT NOT NULL DEFAULT 0,
                    trivias_ganadas      INT NOT NULL DEFAULT 0,
                    correctas_totales    INT NOT NULL DEFAULT 0,
                    incorrectas_totales  INT NOT NULL DEFAULT 0,
                    tiempo_total_anual   INT NOT NULL DEFAULT 0,
                    posicion             INT NULL,
                    es_ganador_anual     TINYINT(1) NOT NULL DEFAULT 0,
                    actualizado_en       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_ra_anio_emp (anio, empleado_id),
                    INDEX idx_ra_anio_puntos (anio, puntos_anuales)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            print("[created] tabla trivia_ranking_anual")
        else:
            print("[skip] tabla trivia_ranking_anual ya existe")

        db.commit()
        print("[done] migration 20260524_01_trivia_operativa")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
