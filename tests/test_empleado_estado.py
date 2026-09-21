import pytest
from repositories import empleado_repository as repo


@pytest.mark.parametrize('estado,activo', [('activo', 1), ('eventual', 1), ('inactivo', 0), ('suspendido', 0)])
@pytest.mark.parametrize('operation', ['create', 'update'])
def test_estado_y_habilitacion_consistentes(monkeypatch, estado, activo, operation):
    class Cursor:
        lastrowid = 42
        def execute(self, sql, params):
            assert sql.count('%s') == len(params)
            if operation == 'create':
                columns = sql.split('(', 1)[1].split(')', 1)[0].split(',')
                values = dict(zip([c.strip() for c in columns], params))
            else:
                columns = sql.split('SET', 1)[1].split('WHERE', 1)[0].split(',')
                values = dict(zip([c.split('=')[0].strip() for c in columns], params))
            assert values['estado'] == estado
            assert values['activo'] == activo
        def close(self): pass
    class Db:
        def cursor(self): return Cursor()
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr(repo, 'get_db', lambda: Db())
    if operation == 'create':
        assert repo.create({'estado': estado}) == 42
    else:
        repo.update(42, {'estado': estado})
