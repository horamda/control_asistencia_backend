import datetime

import app as app_module
import web.app_version.app_version_routes as app_version_routes
import web.auth.decorators as auth_decorators
import services.panel_export_service as panel_export_service


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"


def test_panel_web_muestra_toolbar_de_exportacion(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(
        app_version_routes,
        "get_all",
        lambda: [
            {
                "id": 1,
                "platform": "android",
                "version_minima": "2.0.0",
                "version_recomendada": "2.1.0",
                "url_descarga": "https://example.com/app.apk",
                "mensaje": "Actualice la app",
                "activo": 1,
                "updated_at": datetime.datetime(2026, 6, 15, 10, 0, 0),
            }
        ],
    )

    resp = client.get("/app-version/")

    assert resp.status_code == 200
    assert b"export=xlsx" in resp.data
    assert b"export=pdf" in resp.data


def test_panel_web_exporta_app_version_en_xlsx_y_pdf(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(
        app_version_routes,
        "get_all",
        lambda: [
            {
                "id": 1,
                "platform": "android",
                "version_minima": "2.0.0",
                "version_recomendada": "2.1.0",
                "url_descarga": "https://example.com/app.apk",
                "mensaje": "Actualice la app",
                "activo": 1,
                "updated_at": datetime.datetime(2026, 6, 15, 10, 0, 0),
            }
        ],
    )
    monkeypatch.setattr(
        panel_export_service,
        "get_app_versions",
        lambda: [
            {
                "id": 1,
                "platform": "android",
                "version_minima": "2.0.0",
                "version_recomendada": "2.1.0",
                "url_descarga": "https://example.com/app.apk",
                "mensaje": "Actualice la app",
                "activo": 1,
                "updated_at": datetime.datetime(2026, 6, 15, 10, 0, 0),
            }
        ],
    )

    xlsx_resp = client.get("/app-version/?export=xlsx")
    assert xlsx_resp.status_code == 200
    assert xlsx_resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert xlsx_resp.data.startswith(b"PK\x03\x04")
    assert "app_version.xlsx" in xlsx_resp.headers.get("Content-Disposition", "")

    pdf_resp = client.get("/app-version/?export=pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.mimetype == "application/pdf"
    assert pdf_resp.data.startswith(b"%PDF")
    assert "app_version.pdf" in pdf_resp.headers.get("Content-Disposition", "")
