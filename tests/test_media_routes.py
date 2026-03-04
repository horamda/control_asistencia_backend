import datetime

import app as app_module
import routes.media_routes as media_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_media_foto_not_found(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(media_routes, "get_profile_photo_bytes_by_dni", lambda dni: None)

    resp = client.get("/media/empleados/foto/30123456")
    assert resp.status_code == 404


def test_media_foto_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(
        media_routes,
        "get_profile_photo_bytes_by_dni",
        lambda dni: {
            "mime_type": "image/jpeg",
            "ext": "jpg",
            "data": b"\xff\xd8\xff\xdb",
            "updated_at": datetime.datetime(2026, 2, 28, 10, 30, 0),
        },
    )

    resp = client.get("/media/empleados/foto/30123456")
    assert resp.status_code == 200
    assert resp.data.startswith(b"\xff\xd8\xff")
    assert "image/jpeg" in resp.headers.get("Content-Type", "")
    assert "max-age=86400" in resp.headers.get("Cache-Control", "")
    assert resp.headers.get("ETag")
