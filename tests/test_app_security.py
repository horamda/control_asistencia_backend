import pytest

import app as app_module


@pytest.mark.parametrize("revision", ["release-test-123", None])
def test_health_identifies_deployed_revision_without_database(monkeypatch, revision):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.delenv("BUILD_REVISION", raising=False)
    if revision:
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", revision)
    else:
        monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    response = app_module.create_app().test_client().get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "revision": revision or "local"}


def test_create_app_requires_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(app_module, "init_db", lambda: None)

    with pytest.raises(app_module.AppConfigError, match="SECRET_KEY no configurada"):
        app_module.create_app()


def test_create_app_requires_jwt_secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "prod_secret_key_0123456789abcdef")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(app_module, "init_db", lambda: None)

    with pytest.raises(app_module.AppConfigError, match="JWT_SECRET no configurada"):
        app_module.create_app()


def test_create_app_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "prod_secret_key_0123456789abcdef")
    monkeypatch.setenv("JWT_SECRET", "demasiado-corta")
    monkeypatch.setattr(app_module, "init_db", lambda: None)

    with pytest.raises(app_module.AppConfigError, match="JWT_SECRET debe tener al menos 32"):
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


def test_api_blueprints_are_declared_as_api(monkeypatch):
    """Una API nueva fuera de API_BLUEPRINTS quedaria con CSRF y errores HTML."""
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()

    assert set(app.blueprints) == {bp.name for bp in app_module.BLUEPRINTS}
    undeclared = {
        name
        for name, blueprint in app.blueprints.items()
        if (blueprint.url_prefix or "").startswith(("/api/", "/auth"))
        and name not in app_module.API_BLUEPRINT_NAMES
    }
    assert undeclared == set()



def test_request_id_reuses_safe_proxy_header_and_rejects_unsafe(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    client = app_module.create_app().test_client()

    generated = client.get("/healthz").headers["X-Request-ID"]
    assert len(generated) == 16

    reused = client.get("/healthz", headers={"X-Request-ID": "railway-abc-12345"})
    assert reused.headers["X-Request-ID"] == "railway-abc-12345"

    # Valores arbitrarios del cliente no se copian a logs ni respuestas.
    for unsafe in ('x" "level":"ERROR', "a" * 200):
        response = client.get("/healthz", headers={"X-Request-ID": unsafe})
        assert response.headers["X-Request-ID"] != unsafe
        assert len(response.headers["X-Request-ID"]) == 16


def test_api_500_includes_request_id_for_support(monkeypatch):
    from flask import Blueprint

    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(app_module, "API_BLUEPRINT_NAMES", frozenset({"boom_api"}))
    app = app_module.create_app()
    boom_api = Blueprint("boom_api", __name__, url_prefix="/api/boom")

    @boom_api.route("/")
    def boom():
        raise RuntimeError("boom")

    app.register_blueprint(boom_api)
    response = app.test_client().get("/api/boom/", headers={"X-Request-ID": "soporte-123456"})

    assert response.status_code == 500
    assert response.json == {"success": False, "error": "Error interno", "request_id": "soporte-123456"}


def test_html_pages_publish_strict_csp_with_nonce_matching_scripts(monkeypatch):
    import re

    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.delenv("CSP_ENFORCE", raising=False)
    response = app_module.create_app().test_client().get("/login")

    assert response.status_code == 200
    # Hasta activar CSP_ENFORCE la politica estricta solo reporta.
    assert response.headers["Content-Security-Policy"] == app_module._CSP_BASE
    policy = response.headers["Content-Security-Policy-Report-Only"]
    nonce = re.search(r"'nonce-([^']+)'", policy).group(1)
    html = response.get_data(as_text=True)
    scripts = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
    assert scripts, "base.html deberia tener scripts inline"
    assert all(f'nonce="{nonce}"' in attrs for attrs in scripts)


def test_csp_enforce_switches_strict_policy_to_blocking(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setenv("CSP_ENFORCE", "1")
    response = app_module.create_app().test_client().get("/login")

    assert "script-src 'self' 'nonce-" in response.headers["Content-Security-Policy"]
    assert "Content-Security-Policy-Report-Only" not in response.headers


def test_csp_report_is_logged(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    logged = []
    monkeypatch.setattr(app.logger, "warning", lambda msg, **kw: logged.append((msg, kw)))

    response = app.test_client().post(
        "/csp-report",
        data='{"csp-report": {"document-uri": "https://x/empleados/", "violated-directive": "script-src-attr"}}',
        content_type="application/csp-report",
    )

    assert response.status_code == 204
    assert logged[0][0] == "csp_violation"
    assert logged[0][1]["extra"]["extra"]["violated_directive"] == "script-src-attr"


def test_templates_have_no_inline_event_handlers():
    """Los handlers inline (onclick=...) quedan bloqueados por la CSP estricta:
    usar los atributos data-* de static/js/page-actions.js o addEventListener."""
    import re
    from pathlib import Path

    handler = re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE)
    offenders = [
        str(path)
        for path in Path(app_module.__file__).parent.joinpath("templates").rglob("*.html")
        if handler.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_htmx_request_redirected_to_login_becomes_full_navigation(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    client = app_module.create_app().test_client()

    htmx = client.get("/empleados/?q=ana", headers={"HX-Request": "true"})
    assert htmx.status_code == 204
    assert htmx.headers["HX-Redirect"].endswith("/login")
    assert "Location" not in htmx.headers

    normal = client.get("/empleados/?q=ana")
    assert normal.status_code == 302
    assert normal.headers["Location"].endswith("/login")
