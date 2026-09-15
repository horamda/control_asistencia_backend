from flask import Flask

import web.auth.decorators as auth_decorators


def test_role_required_allows_explicit_module_permission(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/usuarios/")
    @auth_decorators.role_required("admin")
    def usuarios():
        return "ok"

    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: False)
    monkeypatch.setattr(
        auth_decorators,
        "can_access_module",
        lambda user_id, module, action="ver": module == "usuarios" and action == "ver",
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10

    resp = client.get("/usuarios/")

    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_can_access_module_reuses_user_and_permissions_within_request(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    calls = {"user": 0, "permissions": 0}

    def fake_user(user_id):
        calls["user"] += 1
        return {"id": user_id, "rol": "rrhh", "activo": 1}

    def fake_permissions(user_id):
        calls["permissions"] += 1
        return {"asistencias": {"ver": True, "editar": True}}

    monkeypatch.setattr(auth_decorators, "get_web_user_by_id", fake_user)
    monkeypatch.setattr(auth_decorators, "get_user_permissions", fake_permissions)

    with app.test_request_context("/asistencias/"):
        assert auth_decorators.can_access_module(10, "asistencias") is True
        assert auth_decorators.can_access_module(10, "asistencias", "editar") is True
        assert auth_decorators.can_access_module(10, "asistencias") is True

    assert calls == {"user": 1, "permissions": 1}
