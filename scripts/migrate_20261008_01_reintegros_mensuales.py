"""Add monthly periods without rewriting or merging historical reimbursements."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def migrate_cursor(c):
    additions = {
        "reintegro_solicitudes": {
            "periodo": "DATE NULL",
            "kilometros": "INT NULL",
            "reabierto_hasta": "DATE NULL",
        },
        "reintegro_gastos": {
            "numero_comprobante": "VARCHAR(100) NULL",
            "emisor": "VARCHAR(180) NULL",
        },
    }
    for table, fields in additions.items():
        for column, definition in fields.items():
            c.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
                (table, column),
            )
            row = c.fetchone()
            found = next(iter(row.values())) if isinstance(row, dict) else row[0]
            if not found:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    c.execute(
        "ALTER TABLE reintegro_gastos MODIFY fecha DATE NULL, MODIFY importe DECIMAL(14,2) NULL"
    )
    c.execute(
        "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='reintegro_solicitudes' AND index_name='uq_reintegro_periodo'"
    )
    row = c.fetchone()
    found = next(iter(row.values())) if isinstance(row, dict) else row[0]
    if not found:
        c.execute(
            "ALTER TABLE reintegro_solicitudes ADD UNIQUE KEY uq_reintegro_periodo(empresa_id,empleado_id,periodo)"
        )
    c.execute(
        "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='reintegro_gastos' AND index_name='ix_reintegro_comprobante'"
    )
    row = c.fetchone()
    found = next(iter(row.values())) if isinstance(row, dict) else row[0]
    if not found:
        c.execute(
            "ALTER TABLE reintegro_gastos ADD KEY ix_reintegro_comprobante(emisor,numero_comprobante,activo)"
        )
    for sql in (
        (ROOT / "migrations/20261008_01_reintegros_mensuales.sql")
        .read_text(encoding="utf-8")
        .split(";")
    ):
        if sql.strip():
            c.execute(sql)


def migrate():
    from db import init_orm
    from extensions import get_db

    init_orm()
    connection = get_db()
    c = connection.cursor()
    try:
        c.execute("SET SESSION lock_wait_timeout=5")
        migrate_cursor(c)
        connection.commit()
    finally:
        c.close()
        connection.close()
    print(
        "Periodos mensuales, sectores, odometros y recordatorios instalados. Habilite sectores desde el panel."
    )


if __name__ == "__main__":
    migrate()
