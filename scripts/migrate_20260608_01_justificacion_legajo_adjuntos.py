import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL_TYPE = """
INSERT IGNORE INTO legajo_tipos_evento (
  codigo,
  nombre,
  requiere_rango_fechas,
  permite_adjuntos,
  activo
) VALUES (
  'justificacion',
  'Justificacion de asistencia',
  0,
  1,
  1
)
"""


def _load_indexes(cursor, table_name: str):
    cursor.execute(f"SHOW INDEX FROM {table_name}")
    rows = cursor.fetchall()
    indexes = {}
    for row in rows:
        name = row["Key_name"]
        info = indexes.setdefault(
            name,
            {
                "non_unique": int(row["Non_unique"]),
                "columns": [],
            },
        )
        info["columns"].append((int(row["Seq_in_index"]), row["Column_name"]))
    for info in indexes.values():
        info["columns"] = [column for _, column in sorted(info["columns"], key=lambda item: item[0])]
    return indexes


def _find_index_name(indexes: dict, columns: list[str]):
    expected = list(columns)
    for name, info in indexes.items():
        if info["columns"] == expected:
            return name
    return None


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        indexes = _load_indexes(cursor, "legajo_eventos")
        idx_name = _find_index_name(indexes, ["justificacion_id"])
        if not idx_name:
            cursor.execute(
                "ALTER TABLE legajo_eventos "
                "ADD INDEX idx_legajo_eventos_justificacion (justificacion_id)"
            )

        cursor.execute(DDL_TYPE)
        db.commit()
        print("[done] migration 20260608_01_justificacion_legajo_adjuntos")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
