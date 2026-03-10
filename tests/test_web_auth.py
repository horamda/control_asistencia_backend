import app as app_module
import web.auth.web_auth_routes as web_auth_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    return app.test_client()


def test_web_login_csrf_error_muestra_mensaje_amigable(monkeypatch):
    client = _build_client(monkeypatch)

    called = {"auth_called": False}

    def _fake_authenticate_admin(username, password):
        called["auth_called"] = True
        return None

    monkeypatch.setattr(web_auth_routes, "authenticate_admin", _fake_authenticate_admin)

    resp = client.post("/login", data={"username": "admin", "password": "secret"})
    html = resp.get_data(as_text=True)

    assert resp.status_code == 400
    assert "Sesion expirada o formulario invalido" in html
    assert "Ingreso al panel" in html
    assert called["auth_called"] is False
