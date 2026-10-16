import datetime as dt

import pytest
from repositories import empleado_repository as repo


def _fake_db(monkeypatch, *, antes=(1, None, None), periodos=()):
    """Db falsa: registra cada sentencia y responde las lecturas de periodos."""
    executed = []

    class Cursor:
        lastrowid = 42

        def execute(self, sql, params):
            assert sql.count('%s') == len(params)
            executed.append((" ".join(sql.split()), params))
            self._sql = sql

        def fetchone(self):
            return antes

        def fetchall(self):
            return list(periodos)

        def close(self):
            pass

    class Db:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(repo, 'get_db', lambda: Db())
    return executed


def _empleado_values(executed, operation):
    sql, params = next((s, p) for s, p in executed if s.startswith(('INSERT INTO empleados ', 'UPDATE empleados SET empresa_id')))
    if operation == 'create':
        columns = sql.split('(', 1)[1].split(')', 1)[0].split(',')
        return dict(zip([c.strip() for c in columns], params))
    columns = sql.split('SET', 1)[1].split('WHERE', 1)[0].split(',')
    return dict(zip([c.split('=')[0].strip() for c in columns], params))


def _periodos_escritos(executed):
    return [(s.split()[0], p) for s, p in executed if 'empleado_periodos_laborales' in s and not s.startswith('SELECT')]


@pytest.mark.parametrize('estado,activo', [('activo', 1), ('eventual', 1), ('inactivo', 0), ('suspendido', 0)])
@pytest.mark.parametrize('operation', ['create', 'update'])
def test_estado_y_habilitacion_consistentes(monkeypatch, estado, activo, operation):
    # Antes estaba en el mismo estado, asi que la edicion no exige fecha de baja.
    executed = _fake_db(monkeypatch, antes=(activo, None, None))
    if operation == 'create':
        assert repo.create({'estado': estado}) == 42
    else:
        repo.update(42, {'estado': estado})
    values = _empleado_values(executed, operation)
    assert values['estado'] == estado
    assert values['activo'] == activo


def test_alta_activa_abre_periodo_desde_el_ingreso(monkeypatch):
    executed = _fake_db(monkeypatch)
    repo.create({'estado': 'activo', 'fecha_ingreso': '2026-02-01'})
    assert _periodos_escritos(executed) == [('INSERT', (42, dt.date(2026, 2, 1), None))]


def test_alta_inactiva_sin_baja_no_crea_periodo(monkeypatch):
    executed = _fake_db(monkeypatch)
    repo.create({'estado': 'inactivo', 'fecha_ingreso': '2026-02-01'})
    assert _periodos_escritos(executed) == []


def test_edicion_a_inactivo_sin_fecha_de_baja_no_escribe(monkeypatch):
    executed = _fake_db(monkeypatch, antes=(1, dt.date(2024, 1, 1), None), periodos=[(7, dt.date(2024, 1, 1), None)])
    with pytest.raises(repo.periodos_svc.PeriodoLaboralError):
        repo.update(42, {'estado': 'inactivo', 'fecha_ingreso': '2024-01-01'})
    assert not [s for s, _ in executed if not s.startswith('SELECT')]


def test_baja_cierra_el_periodo_vigente(monkeypatch):
    executed = _fake_db(monkeypatch, antes=(dt.date(2024, 1, 1),), periodos=[(7, dt.date(2024, 1, 1), None)])
    repo.dar_de_baja(42, dt.date(2026, 10, 10))
    assert _periodos_escritos(executed) == [('UPDATE', (dt.date(2024, 1, 1), dt.date(2026, 10, 10), 7, 42))]
    assert any("SET activo = 0, estado = 'inactivo', fecha_baja = %s" in s for s, _ in executed)


def test_reingreso_abre_periodo_nuevo_y_conserva_el_anterior(monkeypatch):
    executed = _fake_db(monkeypatch, periodos=[(7, dt.date(2024, 1, 1), dt.date(2026, 3, 31))])
    repo.reincorporar(42, dt.date(2026, 6, 1))
    assert _periodos_escritos(executed) == [('INSERT', (42, dt.date(2026, 6, 1), None))]
    assert any("SET activo = 1, estado = 'activo', fecha_baja = NULL" in s for s, _ in executed)
