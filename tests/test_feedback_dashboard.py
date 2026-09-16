import datetime as dt
from unittest.mock import Mock

import pytest

import services.feedback_dashboard_service as service
import repositories.feedback_dashboard_repository as repository
from repositories.feedback_repository import _build_where


def branches():
    return [dict(id=2, empresa_id=1, nombre='DOLORES', empresa_nombre='A'),
            dict(id=3, empresa_id=1, nombre=' Chascomús ', empresa_nombre='A'),
            dict(id=4, empresa_id=1, nombre='Centro', empresa_nombre='A'),
            dict(id=5, empresa_id=2, nombre='CHASCOMUS', empresa_nombre='B')]


def test_groups_only_within_company_and_preserves_original_catalog():
    original = branches()
    groups = service.branch_groups(original)
    assert len(groups) == 3
    assert service.resolve_branch(groups, 3) == (2, [2, 3])
    assert service.resolve_branch(groups, 5) == (5, [5])
    assert service.resolve_branch(groups, 99) == (99, [])
    assert original[1]['nombre'] == ' Chascomús '


@pytest.mark.parametrize('months,start', [(1, dt.date(2026, 1, 1)), (6, dt.date(2025, 8, 1)), (12, dt.date(2025, 2, 1))])
def test_period_defaults_cross_year(months, start):
    assert service.parse_period({'periodo': str(months)}, default=True, today=dt.date(2026, 1, 15)) == (start, dt.date(2026, 1, 15))


@pytest.mark.parametrize('args', [dict(desde='bad', hasta='2026-01-01'), dict(desde='2026-01-01'),
    dict(desde='2026-02-01', hasta='2026-01-01'), dict(desde='2020-01-01', hasta='2026-01-01'),
    dict(desde='2026-01-01', hasta='2027-01-01')])
def test_invalid_period_is_rejected(args):
    with pytest.raises(ValueError):
        service.parse_period(args, today=dt.date(2026, 1, 15))


def test_empty_months_and_grouped_counts_match_total(monkeypatch):
    monkeypatch.setattr(service, 'get_dashboard_data', lambda **kw: dict(
        resumen=dict(total=5, resueltos=2, resueltos_en_sla=1, resueltos_fuera_sla=1),
        meses=[dict(mes='2026-01', total=2), dict(mes='2026-03', total=3)],
        sucursales=[dict(sucursal_id=2, total=2, resueltos=1, vencidos=0),
                    dict(sucursal_id=3, total=3, resueltos=1, vencidos=2)],
        top_motivos=[], ranking=[]))
    data = service.build_dashboard(desde=dt.date(2026, 1, 15), hasta=dt.date(2026, 3, 20), groups=service.branch_groups(branches()))
    assert [m['total'] for m in data['meses']] == [2, 0, 3]
    assert data['meses'][0]['desde'] == '2026-01-15'
    assert data['meses'][-1]['hasta'] == '2026-03-20'
    assert data['meses'][1]['parcial'] is False
    assert len(data['sucursales']) == 1
    assert data['sucursales'][0]['nombre'] == 'Dolores'
    assert data['sucursales'][0]['total'] == data['resumen']['total'] == 5
    assert data['sucursales'][0]['resueltos_pct'] == 40
    assert data['resumen']['sla_pct'] == 50


def test_blocked_scope_never_queries_and_has_no_sla(monkeypatch):
    query = Mock()
    monkeypatch.setattr(service, 'get_dashboard_data', query)
    data = service.build_dashboard(desde=dt.date(2026, 1, 1), hasta=dt.date(2026, 1, 31), groups=[], blocked=True)
    query.assert_not_called()
    assert data['resumen']['total'] == 0
    assert data['resumen']['sla_pct'] is None


def test_aggregates_use_identical_scope_and_dates_and_limit_ranking(monkeypatch):
    db = Mock()
    cursor = db.cursor.return_value
    cursor.fetchone.return_value = {'total': 0}
    cursor.fetchall.return_value = []
    monkeypatch.setattr(repository, 'get_db', lambda: db)
    repository.get_dashboard_data(desde=dt.date(2026, 1, 1), hasta=dt.date(2026, 1, 31), sector_id=8, sucursal_ids=[2, 3], empleado_activo=0)
    calls = cursor.execute.call_args_list
    assert len(calls) == 5
    for call in calls:
        sql, params = call.args
        assert params == (8, 2, 3, 0, dt.date(2026, 1, 1), dt.date(2026, 2, 1))
        assert 'COALESCE(f.sucursal_id, ee.sucursal_id) IN (%s,%s)' in sql
        assert 'f.created_at >= %s AND f.created_at < %s' in sql
    assert 'LIMIT 10' in calls[-1].args[0]
    db.close.assert_called_once()


def test_empty_branch_selection_does_not_expand_access():
    sql, params = _build_where(sector_id=7, sucursal_ids=[])
    assert '1 = 0' in sql
    assert params == [7]
