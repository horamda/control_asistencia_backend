import datetime as dt
from unittest.mock import Mock

import pytest
import services.vacaciones_service as service
import repositories.vacaciones_repository as repository


@pytest.mark.parametrize('year,ingreso,baja', [
    (2026, '2020-01-01', None), (2026, '2026-08-01', None),
    (2026, '2026-08-01', '2026-08-20'), (2025, '2020-01-01', None),
    (2027, '2020-01-01', None), (2026, '2027-01-01', None),
])
def test_batch_matches_individual_summary(monkeypatch, year, ingreso, baja):
    employee = dict(id=1, empresa_id=2, activo=1, fecha_ingreso=ingreso, fecha_baja=baja)
    days = [dt.date(year, 8, day) for day in range(1, 32)]
    movements = [dict(empleado_id=1, empresa_id=2, tipo='tomado', estado='aprobado', dias=2),
                 dict(empleado_id=1, empresa_id=2, tipo='tomado', estado='pendiente', dias=1),
                 dict(empleado_id=1, empresa_id=2, tipo='ajuste', estado='aprobado', dias=3),
                 dict(empleado_id=1, empresa_id=2, tipo='tomado', estado='aprobado', dias=99, origen_movimiento_id=4)]
    monkeypatch.setattr(service, '_today', lambda: dt.date(2026, 9, 15))
    monkeypatch.setattr(service, 'get_empleado_for_vacaciones', lambda _: employee)
    monkeypatch.setattr(service, 'get_movimientos_by_empleado_anio', lambda **kw: movements)
    monkeypatch.setattr(service, 'count_dias_efectivamente_trabajados', lambda **kw: sum(
        kw['fecha_desde'] <= d.isoformat() <= kw['fecha_hasta'] for d in days))
    expected = service.calcular_resumen_vacaciones(1, year)
    loader = Mock(return_value=(
        [dict(empleado_id=1, empresa_id=2, fecha=day) for day in days] +
        [dict(empleado_id=1, empresa_id=99, fecha=dt.date(year, 7, 1))],
        movements + [dict(empleado_id=1, empresa_id=99, tipo='ajuste', dias=99)],
    ))
    monkeypatch.setattr(service, 'get_resumen_inputs_batch', loader)
    assert service.calcular_resumenes_vacaciones([employee], year) == {1: expected}
    loader.assert_called_once_with([1], year)


def test_batch_skips_inactive_and_invalid_dates(monkeypatch):
    loader = Mock(return_value=([], []))
    monkeypatch.setattr(service, 'get_resumen_inputs_batch', loader)
    assert service.calcular_resumenes_vacaciones([], 2026) == {}
    assert service.calcular_resumenes_vacaciones([{'id': 1, 'activo': 0, 'empresa_id': 1}], 2026) == {}
    loader.assert_not_called()
    assert service.calcular_resumenes_vacaciones([{'id': 2, 'activo': 1, 'empresa_id': 1}], 2026) == {2: None}


def test_repository_reads_whole_page_in_two_queries(monkeypatch):
    db = Mock()
    db.cursor.return_value.fetchall.side_effect = [[], []]
    monkeypatch.setattr(repository, 'get_db', lambda: db)
    assert repository.get_resumen_inputs_batch(range(1, 101), 2026) == ([], [])
    assert db.cursor.return_value.execute.call_count == 2
    for call in db.cursor.return_value.execute.call_args_list:
        query, params = call.args
        assert query.count('%s') == len(params)
        assert params[:100] == tuple(range(1, 101))
    db.close.assert_called_once()
