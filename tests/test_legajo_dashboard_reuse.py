import datetime

import pytest
from flask import Flask
from web.legajos import legajos_routes as routes


@pytest.mark.parametrize('historical,incomplete,expected_calls', [
    (False, False, 1), (True, False, 2), (False, True, 2),
])
def test_dashboard_reuses_only_complete_calendar_range(monkeypatch, historical, incomplete, expected_calls):
    today = datetime.date.today()
    selected = today - datetime.timedelta(days=800 if historical else 2)
    outside = today - datetime.timedelta(days=5)
    calls = []
    period_rows = [{'fecha': selected, 'estado': 'ok', 'metodo_entrada': 'manual'}]
    def attendance(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            rows = ([] if historical else period_rows) + [{'fecha': outside, 'estado': 'tarde'}]
            return rows, 50001 if incomplete else len(rows)
        return period_rows, len(period_rows)
    monkeypatch.setattr(routes, '_get_asistencias_page', attendance)
    monkeypatch.setattr(routes, '_get_justificaciones_page', lambda *a, **k: ([], 0))
    monkeypatch.setattr(routes, '_get_vacaciones_page', lambda *a, **k: ([], 0))
    monkeypatch.setattr(routes, '_compute_vacaciones_resumen_dashboard', lambda *a: {})
    monkeypatch.setattr(routes, '_get_horas_teoricas_por_dia_semana', lambda *a: None)
    with Flask(__name__).app_context():
        result = routes._compute_asistencia_stats(7, selected.isoformat(), selected.isoformat())
    assert len(calls) == expected_calls
    assert result['_rows'] == period_rows
    assert result['asistencia']['totales']['registros'] == 1
    assert result['asistencia']['totales']['tarde'] == 0
