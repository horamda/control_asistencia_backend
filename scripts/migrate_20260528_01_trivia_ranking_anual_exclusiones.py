import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import get_raw_connection, init_orm


SQL = """
CREATE TABLE IF NOT EXISTS trivia_ranking_anual_exclusiones (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    anio        SMALLINT NOT NULL,
    empleado_id INT NOT NULL,
    motivo      VARCHAR(300) NULL,
    creado_por  INT NULL,
    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_trae_anio_empleado (anio, empleado_id),
    KEY idx_trae_anio (anio),
    KEY idx_trae_empleado (empleado_id),
    FOREIGN KEY (empleado_id) REFERENCES empleados(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def main():
    init_orm()
    conn = get_raw_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(SQL)
        conn.commit()
        print("[ok] tabla trivia_ranking_anual_exclusiones lista")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
