import app as app_module
import routes.auth_routes as auth_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_auth_login_requires_json_fields(monkeypatch):
    client = _build_client(monkeypatch)

    resp = client.post(
        "/auth/login",
        data="not-json",
        content_type="application/json",
    )
    body = resp.get_json()

    assert resp.status_code == 400
    assert "DNI y contras" in body["error"]


def test_auth_login_invalid_credentials_sanitized(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(
        auth_routes,
        "authenticate_user",
        lambda dni, password: (None, "bad_password"),
    )

    resp = client.post("/auth/login", json={"dni": "123", "password": "x"})
    body = resp.get_json()

    assert resp.status_code == 401
    assert body["error"] == "Credenciales invalidas."
