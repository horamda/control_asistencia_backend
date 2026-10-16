import datetime
import sqlite3

import pytest

from repositories.premio_concurso_repository import _build_resultado_filters
from web.dashboard_metrics import _justification_period_counts
from scripts.migrate_20260915_02_panel_indexes import covering_index


@pytest.mark.parametrize('start,end', [
    (datetime.date(2026, 9, 1), datetime.date(2026, 9, 15)),
    ('2026-09-01', '2026-09-15'),
    (datetime.datetime(2026, 9, 1, 12), datetime.datetime(2026, 9, 15, 12)),
])
def test_justification_counts_include_whole_last_day_and_null_status(start, end):
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript("""
            CREATE TABLE empleados (id INTEGER PRIMARY KEY, estado TEXT);
            CREATE TABLE empleado_periodos_laborales (empleado_id INTEGER, fecha_desde TEXT, fecha_hasta TEXT);
            CREATE TABLE justificaciones (empleado_id INTEGER, fecha TEXT, fecha_desde TEXT, created_at TEXT, estado TEXT);
            INSERT INTO empleados VALUES (1, 'activo'), (2, 'inactivo');
            INSERT INTO empleado_periodos_laborales VALUES (1, '2020-01-01', NULL), (2, '2020-01-01', '2026-08-31');
            INSERT INTO justificaciones VALUES
                (1, '2026-08-31', NULL, '2026-08-31 23:59:59', 'aprobada'),
                (1, '2026-09-01', NULL, '2026-09-01 00:00:00', NULL),
                (1, '2026-09-15', NULL, '2026-09-15 23:59:59.999999', 'APROBADA'),
                (1, '2026-09-15', NULL, '2026-09-15 12:00:00', 'rechazada'),
                (1, '2026-09-05', NULL, '2026-09-05 12:00:00', 'otro'),
                (1, '2026-09-16', NULL, '2026-09-16 00:00:00', 'pendiente'),
                -- Ausencia posterior a la baja del empleado 2: no cuenta.
                (2, '2026-09-10', NULL, '2026-09-10 12:00:00', 'pendiente');
        """)

        class Cursor:
            calls = 0

            def execute(self, query, params):
                self.calls += 1
                self.result = connection.execute(query.replace('%s', '?'), tuple(str(p) for p in params))

            def fetchone(self):
                return self.result.fetchone()

        cursor = Cursor()
        assert _justification_period_counts(cursor, start, end) == (4, 1, 1, 1)
        assert cursor.calls == 1
    finally:
        connection.close()


@pytest.mark.parametrize('year,month,expected', [
    (2024, 2, ['2024-02-01', '2024-02-29']),
    (2026, None, ['2026-01-01', '2026-12-31']),
    (9999, 12, ['9999-12-01', '9999-12-31']),
])
def test_premios_period_filters_cover_boundaries(year, month, expected):
    where, params = _build_resultado_filters(periodo_year=year, periodo_month=month)
    assert params == expected
    assert 'YEAR(' not in where and 'MONTH(' not in where
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE TABLE premios_resultados (periodo TEXT)')
        connection.executemany('INSERT INTO premios_resultados VALUES (?)', [(value,) for value in expected + ['2000-01-01']])
        rows = connection.execute('SELECT periodo FROM premios_resultados r ' + where.replace('%s', '?'), params).fetchall()
        assert [r[0] for r in rows] == expected
    finally:
        connection.close()


def test_month_without_year_still_matches_all_years():
    where, params = _build_resultado_filters(periodo_month=2)
    assert 'MONTH(r.periodo)' in where
    assert params == [2]


def test_migration_detects_equivalent_and_longer_indexes():
    assert covering_index({'custom': ['fecha', 'estado', 'id']}, ('fecha', 'estado')) == 'custom'
    assert covering_index({'short': ['fecha'], 'reversed': ['estado', 'fecha']}, ('fecha', 'estado')) is None
