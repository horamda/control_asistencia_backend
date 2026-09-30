import sqlite3

import pytest

from repositories import compensatorios_repository as repo
from services import vacaciones_service as service


@pytest.fixture
def policy_db(monkeypatch):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE empleados (id INTEGER PRIMARY KEY, empresa_id INTEGER, activo INTEGER, puesto_id INTEGER);
        CREATE TABLE empleado_puestos (empleado_id INTEGER, puesto_id INTEGER, activo INTEGER);
        CREATE TABLE vacaciones_compensatorios_empleados (empleado_id INTEGER, empresa_id INTEGER, habilitado INTEGER);
        CREATE TABLE vacaciones_compensatorios_puestos (puesto_id INTEGER, empresa_id INTEGER, bloqueado INTEGER);
        INSERT INTO empleados VALUES (1,1,1,10),(2,1,1,20),(3,1,1,20),(4,1,1,20),(5,1,0,20),(6,2,1,20);
        INSERT INTO vacaciones_compensatorios_empleados VALUES (1,1,1),(2,1,1),(3,1,1),(5,1,1),(6,1,1);
        INSERT INTO vacaciones_compensatorios_puestos VALUES (10,1,1);
        INSERT INTO empleado_puestos VALUES (3,10,1),(2,10,0);
    ''')
    class Cursor:
        def __init__(self): self.c = db.cursor()
        def execute(self, sql, params=()): self.c.execute(sql.replace('%s', '?'), params)
        def fetchone(self): return self.c.fetchone()
        def fetchall(self): return self.c.fetchall()
        def close(self): self.c.close()
    class Connection:
        def cursor(self, **kwargs): return Cursor()
        def close(self): pass
    monkeypatch.setattr(repo, 'get_db', Connection)
    yield db
    db.close()


def test_exclusion_puesto_prevalece_y_habilitacion_es_explicita(policy_db):
    assert not repo.habilitado(1)  # Puesto principal excluido.
    assert repo.habilitado(2)  # Puesto adicional inactivo no bloquea.
    assert not repo.habilitado(3)  # Puesto adicional activo excluido.
    assert not repo.habilitado(4)  # Nunca habilitado.
    assert not repo.habilitado(5)  # Empleado inactivo.
    assert not repo.habilitado(6)  # Cambio de empresa invalida permiso anterior.
    habilitados, puestos, bloqueados = repo.get_config()
    assert habilitados == {1, 2, 3}
    assert puestos == {10}
    assert bloqueados == {1, 3}


@pytest.mark.parametrize('operation', ['crear', 'editar', 'aprobar', 'masivo'])
def test_todas_las_acreditaciones_validan_habilitacion(monkeypatch, operation):
    monkeypatch.setattr(service, 'compensatorios_habilitados', lambda eid: False)
    monkeypatch.setattr(service, '_get_empleado_activo', lambda eid: {'id': eid, 'empresa_id': 1})
    monkeypatch.setattr(service, 'get_movimiento_by_id', lambda mid: {'id': mid, 'empleado_id': 1, 'estado': 'pendiente', 'tipo': 'compensatorio'})
    def no_write(*args, **kwargs):
        pytest.fail('No debe guardar compensatorios para un empleado no habilitado')
    for name in ('create_movimiento', 'update_movimiento', 'update_movimiento_estado'):
        monkeypatch.setattr(service, name, no_write)
    data = dict(empleado_id=1, anio=2026, tipo='compensatorio', dias=3)
    if operation == 'masivo':
        ok, errors = service.crear_compensatorios_bulk(empleado_ids=[1], dias=3, anio=2026)
        assert ok == 0 and len(errors) == 1
    else:
        with pytest.raises(service.VacacionesError, match='no habilitado'):
            if operation == 'crear': service.crear_movimiento_vacaciones_admin(data)
            elif operation == 'editar': service.editar_movimiento_vacaciones_pendiente(9, data)
            else: service.aprobar_movimiento_vacaciones(9)
