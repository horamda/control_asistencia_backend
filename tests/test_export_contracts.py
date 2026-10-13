import inspect
import pytest
from flask import Flask
from services import panel_export_service as service


@pytest.mark.parametrize('endpoint', sorted(service.EXPORT_SPECS))
def test_export_loader_arguments_match_repository(monkeypatch, endpoint):
    def all_rows(getter, *args, **kwargs):
        inspect.signature(getter).bind(*args, **kwargs)
        return []
    def page_rows(getter, *args, **kwargs):
        inspect.signature(getter).bind(1, 10001, *args, **kwargs)
        return []
    monkeypatch.setattr(service, '_all_rows', all_rows)
    monkeypatch.setattr(service, '_page_rows', page_rows)
    monkeypatch.setattr(service, 'get_organigrama', lambda **kw: [])
    with Flask(__name__).test_request_context('/?sector_id=1&anio=2026&mes=10'):
        assert service.EXPORT_SPECS[endpoint].loader() == []


def test_page_limit_rejects_total_before_building_file():
    from services.table_export_service import ExportLimitError
    with Flask(__name__).test_request_context('/?export=pdf'):
        with pytest.raises(ExportLimitError):
            service._page_rows(lambda page, size: ([], 2001))


def test_export_permission_cannot_be_replaced_by_read_permission(monkeypatch):
    from flask import session
    from werkzeug.exceptions import Forbidden
    app = Flask(__name__)
    app.secret_key = 'test'
    monkeypatch.setattr(service.auth_decorators, 'can_access_module', lambda uid, module, action: action == 'ver')
    with app.test_request_context('/empleados/?export=xlsx'):
        session['user_id'] = 1
        with pytest.raises(Forbidden):
            service._enforce_export_permission()
