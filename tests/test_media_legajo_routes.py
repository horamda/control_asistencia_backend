import app as app_module
import routes.media_routes as media_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_media_legajo_adjunto_requires_session(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.get("/media/legajos/adjunto/10")
    assert resp.status_code == 403


def test_media_legajo_adjunto_ok(monkeypatch, tmp_path):
    client = _build_client(monkeypatch)
    with client.session_transaction() as sess:
        sess["user_id"] = 5

    payload_file = tmp_path / "certificado.pdf"
    payload_file.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(media_routes, "has_any_role", lambda user_id, roles: True)
    monkeypatch.setattr(
        media_routes,
        "get_adjunto_by_id",
        lambda adjunto_id: {
            "id": adjunto_id,
            "estado": "activo",
            "evento_estado": "vigente",
            "storage_backend": "local",
            "storage_ruta": "uploads/legajos/empresa_1/f.pdf",
            "mime_type": "application/pdf",
            "nombre_original": "certificado.pdf",
        },
    )
    monkeypatch.setattr(media_routes, "resolve_legajo_storage_path", lambda storage_ruta: payload_file)

    resp = client.get("/media/legajos/adjunto/10")
    assert resp.status_code == 200
    assert b"%PDF-1.4" in resp.data
    assert "application/pdf" in resp.headers.get("Content-Type", "")


def test_media_legajo_adjunto_ok_db(monkeypatch):
    client = _build_client(monkeypatch)
    with client.session_transaction() as sess:
        sess["user_id"] = 5

    monkeypatch.setattr(media_routes, "has_any_role", lambda user_id, roles: True)
    monkeypatch.setattr(
        media_routes,
        "get_adjunto_by_id",
        lambda adjunto_id: {
            "id": adjunto_id,
            "estado": "activo",
            "evento_estado": "vigente",
            "storage_backend": "db",
            "storage_ruta": "db://legajos/sample.pdf",
            "mime_type": "application/pdf",
            "nombre_original": "certificado.pdf",
        },
    )
    monkeypatch.setattr(media_routes, "get_adjunto_data_by_id", lambda adjunto_id: b"%PDF-1.7 db")

    resp = client.get("/media/legajos/adjunto/10")
    assert resp.status_code == 200
    assert b"%PDF-1.7 db" in resp.data
    assert "application/pdf" in resp.headers.get("Content-Type", "")
