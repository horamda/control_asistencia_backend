"""Authorization and escaped HTML for asynchronous panel alerts."""
from pathlib import Path
from flask import Flask
from web import panel_notifications_routes as routes


def test_alerts_require_active_admin_and_cache_per_user(monkeypatch):
    app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
    app.secret_key = 'test'
    app.register_blueprint(routes.panel_notifications_bp)
    actor = {}
    monkeypatch.setattr(routes, '_cached_web_user', lambda uid: actor or None)
    calls = []
    def build(role):
        calls.append(role)
        return {'total': 1, 'items': [{'tone': 'warning', 'href': '/test', 'label': '<script>bad</script>', 'description': 'Pending', 'count': 1}]}
    monkeypatch.setattr(routes, 'build_panel_notifications', build)
    client = app.test_client()
    assert client.get('/panel/notificaciones').status_code == 401
    actor.update(id=1, empresa_id=1, activo=1, rol='empleado')
    assert client.get('/panel/notificaciones').status_code == 403
    actor['rol'] = 'admin'
    for _ in range(2):
        response = client.get('/panel/notificaciones')
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert '&lt;script&gt;' in response.json['html']
    assert len(calls) == 1
    actor['id'] = 2
    client.get('/panel/notificaciones')
    assert len(calls) == 2
    actor['activo'] = 0
    assert client.get('/panel/notificaciones').status_code == 401
