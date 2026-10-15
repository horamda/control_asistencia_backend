import datetime as dt
from io import BytesIO

import pytest
from openpyxl import load_workbook

from services.asistencia_monthly_report_service import build_monthly_attendance_report
from services.table_export_service import build_table_export, ExportLimitError


def report(**kwargs):
    data = dict(year=2026, month=10, empleados=[{'id': 1, 'activo': 1}], marcas=[], justificaciones=[], today=dt.date(2026, 10, 13))
    data.update(kwargs)
    return build_monthly_attendance_report(**data)


def test_future_month_has_no_absences_or_possible_days():
    result = report(month=11)
    assert result['kpis']['dias_posibles'] == 0
    assert result['ausencias_rows'] == []
    assert all(c['status'] == 'pending' for c in result['planilla_rows'][0]['cells'])


def test_today_is_not_an_absence_and_historical_employment_is_respected():
    result = report(empleados=[{'id': 1, 'activo': 0, 'fecha_ingreso': '2026-10-05', 'fecha_baja': '2026-10-07'}])
    assert result['kpis']['dias_posibles'] == 3
    assert len(result['ausencias_rows']) == 3
    assert all(row['fecha'] < '2026-10-13' for row in report()['ausencias_rows'])


def test_split_shift_excludes_unworked_break():
    marks = [dict(id=i, empleado_id=1, fecha='2026-10-01', hora=time, accion=action) for i, (time, action) in enumerate([('08:00', 'ingreso'), ('12:00', 'egreso'), ('16:00', 'ingreso'), ('20:00', 'egreso')])]
    result = report(marcas=marks)
    assert result['kpis']['horas_trabajadas'] == 8
    assert result['jornada_rows'][0]['horas'] == 8


def test_unmatched_punch_does_not_invent_worked_hours():
    result = report(marcas=[dict(empleado_id=1, fecha='2026-10-01', hora='23:00', accion='ingreso')])
    assert result['kpis']['horas_trabajadas'] == 0
    assert result['kpis']['sin_egreso'] == 1


def test_spreadsheet_text_cannot_become_formula():
    file = build_table_export('=1+1', [{'name': '=HYPERLINK("https://example.com")', 'number': 12}], 'xlsx')
    sheet = load_workbook(BytesIO(file.data)).active
    assert sheet['A1'].data_type == 's'
    assert sheet['A4'].data_type == 's'
    assert sheet['B4'].data_type == 'n'


def test_large_export_is_rejected_not_truncated():
    with pytest.raises(ExportLimitError):
        build_table_export('test', ({'id': n} for n in range(2001)), 'pdf')


def test_csv_formula_protection_preserves_numeric_values():
    import io
    from utils.export_safety import SafeCsvWriter
    stream = io.StringIO()
    SafeCsvWriter(stream).writerow(['=1+1', '\t@SUM(A1)', -15, 'normal'])
    assert stream.getvalue() == "'=1+1,'\t@SUM(A1),-15,normal\r\n"


def test_static_compression_and_cache_version(tmp_path):
    import gzip
    from flask import Flask, url_for
    from utils.static_assets import init_static_assets
    asset = tmp_path / 'test.css'
    asset.write_text('body {color: blue;}' * 100)
    app = Flask(__name__, static_folder=str(tmp_path), static_url_path='/static')
    init_static_assets(app)
    with app.test_request_context():
        url = url_for('static', filename='test.css')
    assert '?v=' in url
    response = app.test_client().get(url, headers={'Accept-Encoding': 'gzip'})
    assert gzip.decompress(response.data) == asset.read_bytes()
    assert response.headers['Content-Encoding'] == 'gzip'
    assert response.cache_control.immutable
    assert 'no-cache' not in response.headers['Cache-Control']
    assert app.test_client().get(url, headers={'Accept-Encoding': 'gzip;q=0'}).data == asset.read_bytes()



def test_static_images_are_versioned_and_cached_without_gzip(tmp_path):
    from flask import Flask, url_for
    from utils.static_assets import init_static_assets
    image = tmp_path / 'logo.png'
    image.write_bytes(bytes([0x89]) + b'PNG' + b'0' * 500)
    app = Flask(__name__, static_folder=str(tmp_path), static_url_path='/static')
    init_static_assets(app)
    with app.test_request_context():
        url = url_for('static', filename='logo.png')
    assert '?v=' in url
    response = app.test_client().get(url, headers={'Accept-Encoding': 'gzip'})
    # Ya comprimidas: no se recomprimen, pero se cachean un ano por version.
    assert 'Content-Encoding' not in response.headers
    assert response.data == image.read_bytes()
    assert response.cache_control.immutable and response.cache_control.max_age == 31536000
    assert 'no-cache' not in response.headers['Cache-Control']
    # Sin la version correcta no se cachea como inmutable (evita servir una vieja).
    assert not app.test_client().get('/static/logo.png?v=otra').cache_control.immutable

def test_company_scope_rejects_cross_company_and_allows_admin(monkeypatch):
    from flask import Flask, session
    from werkzeug.exceptions import Forbidden
    from web.auth import decorators as auth
    app = Flask(__name__)
    app.secret_key = 'test'
    with app.test_request_context():
        session['user_id'] = 1
        monkeypatch.setattr(auth, '_cached_web_user', lambda uid: {'activo': 1, 'rol': 'rrhh', 'empresa_id': 1})
        with pytest.raises(Forbidden):
            auth.require_company_record({'empresa_id': 2})
        assert auth.require_company_record({'empresa_id': 1}) == {'empresa_id': 1}
        monkeypatch.setattr(auth, '_cached_web_user', lambda uid: {'activo': 1, 'rol': 'admin', 'empresa_id': 1})
        assert auth.require_company_record({'empresa_id': 2}) == {'empresa_id': 2}


def test_query_metrics_count_success_and_failure_without_sql(monkeypatch):
    from flask import Flask, g
    from utils.query_metrics import MeasuredCursor
    class Cursor:
        def execute(self, sql, params):
            if sql == 'fail':
                raise ValueError('test')
    with Flask(__name__).test_request_context():
        cursor = MeasuredCursor(Cursor())
        cursor.execute('select', ('private',))
        with pytest.raises(ValueError):
            cursor.execute('fail', ('private',))
        assert g.db_queries == 2
        assert g.db_ms >= 0
        assert 'private' not in repr(vars(g))
