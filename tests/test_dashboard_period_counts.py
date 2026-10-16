import sqlite3

import pytest
from flask import Flask

from web.dashboard_metrics import _attendance_period_counts

PERIODOS_SQL = "CREATE TABLE empleado_periodos_laborales (empleado_id INTEGER, fecha_desde TEXT, fecha_hasta TEXT);"


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.calls = 0

    def execute(self, query, params):
        self.calls += 1
        self.result = self.connection.execute(query.replace("%s", "?"), params)

    def fetchone(self):
        return self.result.fetchone()


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("2026-09-01", "2026-09-15", (5, 1, 2)),
        ("2026-09-15", "2026-09-15", (2, 0, 1)),
        ("2026-10-01", "2026-10-31", (0, 0, 0)),
    ],
)
def test_period_counts_preserve_totals_and_boundaries(start, end, expected):
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(f"""
            CREATE TABLE empleados (id INTEGER PRIMARY KEY);
            CREATE TABLE asistencias (empleado_id INTEGER, fecha TEXT, estado TEXT);
            {PERIODOS_SQL}
            INSERT INTO empleados VALUES (1), (2);
            INSERT INTO empleado_periodos_laborales VALUES (1, '2024-01-01', NULL);
        """)
        connection.executemany(
            "INSERT INTO asistencias VALUES (1, ?, ?)",
            [
                ("2026-08-31", "tarde"),
                ("2026-09-01", "tarde"),
                ("2026-09-02", "ausente"),
                ("2026-09-03", None),
                ("2026-09-15", "ok"),
                ("2026-09-15", "ausente"),
                ("2026-09-16", "ausente"),
            ],
        )
        # Empleado sin periodo laboral (inactivo sin fecha de baja): no suma.
        connection.execute("INSERT INTO asistencias VALUES (2, '2026-09-15', 'ausente')")

        cursor = _Cursor(connection)
        assert _attendance_period_counts(cursor, start, end) == expected
        assert cursor.calls == 1
    finally:
        connection.close()


def test_period_counts_preserve_error_fallback():
    class BrokenCursor:
        def execute(self, query, params):
            raise RuntimeError("database unavailable")

    with Flask(__name__).app_context():
        assert _attendance_period_counts(BrokenCursor(), "2026-09-01", "2026-09-15") == (0, 0, 0)


@pytest.mark.parametrize(
    "filters,expected",
    [
        # Sin filtro tampoco cuentan registros sin empleado ni posteriores a la baja.
        ({}, (4, 2, 2)),
        ({"empresa_id": 1}, (2, 1, 1)),
        ({"sucursal_id": 20}, (1, 0, 1)),
        ({"empresa_id": 1, "sucursal_id": 10}, (1, 1, 0)),
        ({"empresa_id": 2, "sucursal_id": 10}, (0, 0, 0)),
        ({"empresa_id": 999}, (0, 0, 0)),
    ],
)
def test_period_counts_keep_company_and_branch_filters(filters, expected):
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(f"""
            CREATE TABLE empleados (id INTEGER PRIMARY KEY, empresa_id INTEGER, sucursal_id INTEGER);
            CREATE TABLE asistencias (empleado_id INTEGER, fecha TEXT, estado TEXT);
            {PERIODOS_SQL}
            INSERT INTO empleados VALUES (1, 1, 10), (2, 1, 20), (3, 2, 30);
            INSERT INTO empleado_periodos_laborales VALUES
                (1, NULL, '2026-09-10'), (2, '2026-01-01', NULL), (3, '2026-01-01', NULL);
            INSERT INTO asistencias VALUES
                (1, '2026-09-01', 'tarde'), (1, '2026-09-15', NULL),
                (2, '2026-09-05', 'ausente'), (3, '2026-09-05', 'ausente'),
                (3, '2026-09-05', 'tarde'), (999, '2026-09-05', 'ausente'),
                (1, '2026-08-31', 'ausente'), (1, '2026-09-16', 'tarde');
        """)
        # El empleado 1 se dio de baja el 10/09: su registro del 15/09 no cuenta.
        cursor = _Cursor(connection)
        assert _attendance_period_counts(cursor, "2026-09-01", "2026-09-15", **filters) == expected
        assert cursor.calls == 1
    finally:
        connection.close()


def test_period_counts_skip_gap_between_exit_and_rehire():
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(f"""
            CREATE TABLE empleados (id INTEGER PRIMARY KEY);
            CREATE TABLE asistencias (empleado_id INTEGER, fecha TEXT, estado TEXT);
            {PERIODOS_SQL}
            INSERT INTO empleados VALUES (1);
            INSERT INTO empleado_periodos_laborales VALUES
                (1, '2025-01-01', '2026-03-31'), (1, '2026-06-01', NULL);
            INSERT INTO asistencias VALUES
                (1, '2026-03-31', 'ausente'),
                (1, '2026-04-15', 'ausente'),
                (1, '2026-05-31', 'ausente'),
                (1, '2026-06-01', 'tarde');
        """)
        cursor = _Cursor(connection)
        # Cuenta el ultimo dia antes de la baja y el primero del reingreso.
        assert _attendance_period_counts(cursor, "2026-01-01", "2026-12-31") == (2, 1, 1)
    finally:
        connection.close()
