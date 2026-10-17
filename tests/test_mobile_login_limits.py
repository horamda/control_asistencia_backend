from flask import Flask
import routes.mobile_v1_routes as mobile
from utils.limiter import limiter


def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=True, RATELIMIT_STORAGE_URI="memory://")
    limiter.init_app(app)
    app.register_blueprint(mobile.mobile_v1_bp)
    monkeypatch.setattr(mobile, "authenticate_user", lambda *args: (None, "bad_password"))
    return app.test_client()


def test_mobile_login_limits_account_across_ips(monkeypatch):
    c = client(monkeypatch)
    for i in range(10):
        assert c.post('/api/v1/mobile/auth/login', json={'dni':'audit-account','password':'invalid'}, environ_base={'REMOTE_ADDR':f'192.0.2.{i+1}'}).status_code == 401
    assert c.post('/api/v1/mobile/auth/login', json={'dni':'audit-account','password':'invalid'}, environ_base={'REMOTE_ADDR':'192.0.2.99'}).status_code == 429
    assert c.post('/api/v1/mobile/auth/login', json={'dni':'other-account','password':'invalid'}).status_code == 401


def test_successful_shift_logins_do_not_consume_failed_attempt_budget(monkeypatch):
    c = client(monkeypatch)
    import repositories.mobile_sesiones_repository as sessions
    monkeypatch.setattr(mobile, "authenticate_user", lambda *args: ({'id':1,'dni':'audit','nombre':'Audit'}, None))
    monkeypatch.setattr(sessions, "create_sesion", lambda data: 1)
    monkeypatch.setattr(mobile, "_imagen_version_for_dni", lambda dni: None)
    for _ in range(65):
        assert c.post('/api/v1/mobile/auth/login', json={'dni':'audit','password':'valid'}).status_code == 200
