"""Pagination shortcuts must preserve totals and release connections."""
import importlib
import pytest

CASES = [
    ('empleado', 'get_page', {}),
    ('justificacion', 'get_page', {}),
    ('sector', 'get_page', {}),
    ('adelanto', 'get_page_by_empleado', {'empleado_id': 7}),
    ('adelanto', 'get_page', {}),
    ('asistencia_marca', 'get_page_by_empleado', {'empleado_id': 7}),
    ('asistencia_marca', 'get_page_admin', {}),
    ('pedido_mercaderia', 'get_page_by_empleado', {'empleado_id': 7}),
    ('pedido_mercaderia', 'get_page', {}),
    ('vacaciones', 'get_periodos_aprobados_page_by_empleado', {'empleado_id': 7}),
    ('vacaciones', 'get_movimientos_page', {}),
    ('legajo_evento', 'get_tipos_evento_page', {}),
    ('legajo_evento', 'get_eventos_page', {}),
]

@pytest.mark.parametrize('module,function,kwargs', CASES)
@pytest.mark.parametrize('page,size,expected_queries,expected_total', [(1,0,1,0),(1,2,1,2),(1,5,2,17),(2,0,2,17),(2,2,2,17)])
def test_count_only_when_needed(monkeypatch, module, function, kwargs, page, size, expected_queries, expected_total):
    repo = importlib.import_module('repositories.' + module + '_repository')
    rows = [{'id': n} for n in range(size)]
    queries = []
    closed = []
    class Cursor:
        def execute(self, sql, params=()): queries.append((sql, params))
        def fetchall(self): return rows
        def fetchone(self): return {'total':17}
        def close(self): closed.append('cursor')
    class Connection:
        def cursor(self, **kw): return Cursor()
        def close(self): closed.append('db')
    monkeypatch.setattr(repo, 'get_db', Connection)
    if module == 'adelanto': monkeypatch.setattr(repo, '_adelantos_resolution_support', lambda c: (False, False))
    if module == 'pedido_mercaderia': monkeypatch.setattr(repo, '_attach_items', lambda c, rs: rs)
    actual_rows, total = getattr(repo, function)(page=page, per_page=5, **kwargs)
    assert actual_rows == rows
    assert total == expected_total
    queries = [(sql, args) for sql, args in queries if "information_schema" not in sql]
    assert len(queries) == expected_queries
    assert closed == ['cursor', 'db']
    assert 'LIMIT %s OFFSET %s' in queries[0][0]
    assert queries[0][1][-2:] == (5, (page-1)*5)


def test_empty_feedback_skips_detail_query(monkeypatch):
    from repositories import feedback_repository as repo
    queries = []
    closed = []
    class Cursor:
        def execute(self, sql, params): queries.append((sql, params))
        def fetchone(self): return {'total': 0}
        def fetchall(self): raise AssertionError('No rows should be requested')
        def close(self): closed.append('cursor')
    class Connection:
        def cursor(self, **kwargs): return Cursor()
        def close(self): closed.append('db')
    monkeypatch.setattr(repo, 'get_db', Connection)
    assert repo._fetch_page(1, 20, 'WHERE ee.empresa_id = %s', [3]) == ([], 0)
    assert len(queries) == 1
    assert queries[0][1] == (3,)
    assert closed == ['cursor', 'db']
