import pytest

import app as app_module


def test_create_app_requires_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(app_module, "init_db", lambda: None)

    with pytest.raises(app_module.AppConfigError, match="SECRET_KEY no configurada"):
        app_module.create_app()


def test_create_app_configures_session_cookie_security(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setenv("SECRET_KEY", "prod_secret_key_0123456789abcdef")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "ca_session")
    monkeypatch.setenv("SESSION_COOKIE_SAMESITE", "Strict")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    monkeypatch.setenv("SESSION_LIFETIME_MINUTES", "45")

    app = app_module.create_app()

    assert app.config["SECRET_KEY"] == "prod_secret_key_0123456789abcdef"
    assert app.config["SESSION_COOKIE_NAME"] == "ca_session"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_REFRESH_EACH_REQUEST"] is False
    assert int(app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()) == 45 * 60
