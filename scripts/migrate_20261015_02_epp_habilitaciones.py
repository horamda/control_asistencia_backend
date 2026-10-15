"""EPP: disponibilidad por combinacion sector + puesto (epp_articulos.habilitaciones).

Antes un articulo guardaba dos listas independientes (sectores y puestos) y el
empleado debia estar en ambas: se mezclaban puestos de otros sectores. Ahora
cada regla es {"s": sector|null, "p": puesto|null} (p null = todo el sector).
La conversion conserva exactamente el acceso anterior (producto de las listas).
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def legacy_rules(sectores, puestos):
    if sectores and puestos:
        return [{"s": s, "p": p} for s in sectores for p in puestos]
    if sectores:
        return [{"s": s, "p": None} for s in sectores]
    return [{"s": None, "p": p} for p in puestos]


def _load(value):
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value) if isinstance(value, str) else list(value)


def _values(row):
    """Acepta cursores de tuplas o de diccionarios."""
    return list(row.values()) if isinstance(row, dict) else list(row)


def migrate_cursor(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME='epp_articulos' AND COLUMN_NAME='habilitaciones'"
    )
    if not _values(cursor.fetchone())[0]:
        cursor.execute("ALTER TABLE epp_articulos ADD COLUMN habilitaciones JSON NULL AFTER puestos")
    cursor.execute("SELECT id, sectores, puestos FROM epp_articulos WHERE habilitaciones IS NULL")
    for row in cursor.fetchall():
        article_id, sectores, puestos = _values(row)
        rules = legacy_rules(_load(sectores), _load(puestos))
        cursor.execute(
            "UPDATE epp_articulos SET habilitaciones=%s WHERE id=%s",
            (json.dumps(rules, sort_keys=True), article_id),
        )


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
        print("Habilitaciones EPP por sector y puesto instaladas.")
    finally:
        cursor.close()
        connection.close()
