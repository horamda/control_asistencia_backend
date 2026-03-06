import io

import app as app_module
import web.auth.decorators as auth_decorators
import web.legajos.legajos_routes as legajos_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 11


def test_legajos_crear_evento_con_adjunto(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajos_routes, "log_audit", lambda *args, **kwargs: None)

    monkeypatch.setattr(
        legajos_routes,
        "get_empleado_by_id",
        lambda emp_id: {
            "id": emp_id,
            "empresa_id": 3,
            "legajo": "L-99",
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
        },
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_tipo_evento_by_id",
        lambda tipo_id: {
            "id": tipo_id,
            "activo": 1,
            "requiere_rango_fechas": 0,
        },
    )

    captured = {}

    def _fake_create_evento(data):
        captured["evento_data"] = dict(data)
        return 77

    def _fake_save(file_storage, **kwargs):
        captured["saved_kwargs"] = dict(kwargs)
        captured["saved_filename"] = file_storage.filename
        return {
            "nombre_original": "certificado.pdf",
            "mime_type": "application/pdf",
            "extension": "pdf",
            "tamano_bytes": 1234,
            "sha256": "a" * 64,
            "storage_backend": "local",
            "storage_ruta": "uploads/legajos/empresa_3/empleado_7/evento_77/fake.pdf",
        }

    def _fake_create_adjunto(data):
        captured["adjunto_data"] = dict(data)
        return 88

    monkeypatch.setattr(legajos_routes, "create_evento", _fake_create_evento)
    monkeypatch.setattr(legajos_routes, "save_legajo_attachment_local", _fake_save)
    monkeypatch.setattr(legajos_routes, "create_adjunto", _fake_create_adjunto)

    resp = client.post(
        "/legajos/empleado/7/eventos",
        data={
            "tipo_id": "1",
            "fecha_evento": "2026-03-05",
            "descripcion": "Certificado por enfermedad",
            "adjuntos": (io.BytesIO(b"%PDF-1.4"), "certificado.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/legajos/empleado/7")
    assert captured["evento_data"]["empresa_id"] == 3
    assert captured["evento_data"]["empleado_id"] == 7
    assert captured["saved_filename"] == "certificado.pdf"
    assert captured["saved_kwargs"]["empresa_id"] == 3
    assert captured["saved_kwargs"]["empleado_id"] == 7
    assert captured["saved_kwargs"]["evento_id"] == 77
    assert captured["adjunto_data"]["evento_id"] == 77
    assert captured["adjunto_data"]["empresa_id"] == 3
    assert captured["adjunto_data"]["empleado_id"] == 7


def test_legajos_editar_evento(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajos_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        legajos_routes,
        "get_empleado_by_id",
        lambda emp_id: {
            "id": emp_id,
            "empresa_id": 3,
            "legajo": "L-99",
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
        },
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_evento_by_id",
        lambda evento_id: {
            "id": evento_id,
            "empleado_id": 7,
            "tipo_id": 1,
            "fecha_evento": None,
            "fecha_desde": None,
            "fecha_hasta": None,
            "titulo": "Viejo titulo",
            "descripcion": "Vieja descripcion",
            "severidad": "leve",
            "justificacion_id": None,
        },
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_tipo_evento_by_id",
        lambda tipo_id: {"id": tipo_id, "activo": 1, "requiere_rango_fechas": 0},
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_tipos_evento",
        lambda include_inactive=False: [{"id": 1, "nombre": "Amonestacion"}],
    )

    captured = {}
    monkeypatch.setattr(
        legajos_routes,
        "update_evento",
        lambda evento_id, data: captured.update({"evento_id": evento_id, "data": dict(data)}),
    )

    resp = client.post(
        "/legajos/empleado/7/eventos/44/editar",
        data={
            "tipo_id": "1",
            "fecha_evento": "2026-03-06",
            "descripcion": "Descripcion editada",
            "titulo": "Titulo editado",
            "severidad": "media",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/legajos/empleado/7")
    assert captured["evento_id"] == 44
    assert captured["data"]["descripcion"] == "Descripcion editada"
    assert captured["data"]["severidad"] == "media"


def test_legajos_anular_evento(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajos_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        legajos_routes,
        "get_empleado_by_id",
        lambda emp_id: {
            "id": emp_id,
            "empresa_id": 3,
            "legajo": "L-99",
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
        },
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_evento_by_id",
        lambda evento_id: {
            "id": evento_id,
            "empleado_id": 7,
            "estado": "vigente",
        },
    )
    captured = {}
    monkeypatch.setattr(
        legajos_routes,
        "anular_evento",
        lambda evento_id, actor_id, motivo: captured.update(
            {"evento_id": evento_id, "actor_id": actor_id, "motivo": motivo}
        ),
    )

    resp = client.post(
        "/legajos/empleado/7/eventos/44/anular",
        data={"motivo_anulacion": "Documento invalido"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/legajos/empleado/7")
    assert captured["evento_id"] == 44
    assert captured["actor_id"] == 11
    assert captured["motivo"] == "Documento invalido"


def test_legajos_eliminar_adjunto(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajos_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        legajos_routes,
        "get_empleado_by_id",
        lambda emp_id: {
            "id": emp_id,
            "empresa_id": 3,
            "legajo": "L-99",
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
        },
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_evento_by_id",
        lambda evento_id: {
            "id": evento_id,
            "empleado_id": 7,
            "estado": "vigente",
        },
    )
    monkeypatch.setattr(
        legajos_routes,
        "get_adjunto_by_id",
        lambda adjunto_id: {
            "id": adjunto_id,
            "evento_id": 44,
            "estado": "activo",
        },
    )
    captured = {}
    monkeypatch.setattr(
        legajos_routes,
        "mark_deleted",
        lambda adjunto_id, actor_id: captured.update({"adjunto_id": adjunto_id, "actor_id": actor_id}),
    )

    resp = client.post(
        "/legajos/empleado/7/eventos/44/adjuntos/99/eliminar",
        data={},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/legajos/empleado/7")
    assert captured["adjunto_id"] == 99
    assert captured["actor_id"] == 11
