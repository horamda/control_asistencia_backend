import importlib
import pytest
from flask import Flask
from flask_wtf.csrf import CSRFProtect, generate_csrf
import web.auth.decorators as auth

MODULES = [('empleados.empleados_routes', 'empleados_bp'), ('empresas.empresas_routes', 'empresas_bp'), ('horarios.horarios_routes', 'horarios_bp'), ('legajos.legajo_tipos_evento_routes', 'legajo_tipos_evento_bp'), ('puestos.puestos_routes', 'puestos_bp'), ('sectores.sectores_routes', 'sectores_bp'), ('sucursales.sucursales_routes', 'sucursales_bp'), ('usuarios.usuarios_routes', 'usuarios_bp')]


@pytest.mark.parametrize('module,blueprint', MODULES)
def test_mutations_require_post_csrf_and_write_permission(monkeypatch, module, blueprint):
    app = Flask(__name__)
    app.secret_key = 'isolated-security-regression'
    CSRFProtect(app)
    app.register_blueprint(getattr(importlib.import_module('web.' + module), blueprint))
    app.add_url_rule('/token', view_func=lambda: generate_csrf())
    monkeypatch.setattr(auth, 'has_role', lambda *args: False)
    monkeypatch.setattr(auth, 'can_access_module', lambda uid, module, action: action == 'ver')
    client = app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = 123
    token = client.get('/token').text
    rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint.endswith(('.activar', '.desactivar'))]
    assert len(rules) == 2
    for rule in rules:
        url = str(rule)
        for argument in rule.arguments:
            url = url.replace('<int:' + argument + '>', '1')
        assert client.get(url).status_code == 405
        assert client.post(url).status_code == 400
        assert client.post(url, data={'csrf_token': token}).status_code == 403
