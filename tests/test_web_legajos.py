import io

import app as app_module
import web.auth.decorators as auth_decorators
import web.legajos.legajos_routes as legajos_routes
import web.legajos.legajo_tipos_evento_routes as legajo_tipos_evento_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 11


def test_legajos_listado_eventos(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    with client.session_transaction() as sess:
        sess["user_role"] = "admin"
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        legajos_routes,
        "get_eventos_page",
        lambda **kwargs: (
            [
                {
                    "id": 44,
                    "empresa_id": 3,
                    "empresa_nombre": "Empresa A",
                    "empleado_id": 7,
                    "empleado_apellido": "Perez",
                    "empleado_nombre": "Ana",
                    "empleado_legajo": "L-99",
                    "empleado_dni": "30123456",
                    "empleado_foto": None,
                    "tipo_nombre": "Certificado medico",
                    "fecha_evento": "2026-03-05",
                    "titulo": "Certificado",
                    "estado": "vigente",
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(legajos_routes, "get_empresas", lambda include_inactive=True: [{"id": 3, "razon_social": "Empresa A"}])
    monkeypatch.setattr(
        legajos_routes,
        "get_empleados",
        lambda include_inactive=True: [{"id": 7, "apellido": "Perez", "nombre": "Ana", "dni": "30123456"}],
    )
    monkeypatch.setattr(legajos_routes, "get_tipos_evento", lambda include_inactive=True: [{"id": 1, "nombre": "Certificado medico"}])

    resp = client.get("/legajos/eventos/?empresa_id=3")
    assert resp.status_code == 200
    assert b"Certificado medico" in resp.data
    assert b"/legajos/empleado/7" in resp.data


def test_legajos_listado_muestra_foto_y_fallback(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        legajos_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {
                "id": 7,
                "empresa_id": 3,
                "empresa_nombre": "Empresa A",
                "legajo": "L-99",
                "dni": "30123456",
                "nombre": "Ana",
                "apellido": "Perez",
                "activo": 1,
                "foto": "https://cdn.example.com/fotos/30123456.jpg",
            },
            {
                "id": 8,
                "empresa_id": 3,
                "empresa_nombre": "Empresa A",
                "legajo": "L-100",
                "dni": "30123457",
                "nombre": "Juan",
                "apellido": "Lopez",
                "activo": 1,
                "foto": None,
            },
        ],
    )

    resp = client.get("/legajos/")
    assert resp.status_code == 200
    assert b"https://cdn.example.com/fotos/30123456.jpg" in resp.data
    assert b"img/empleado-default.svg" in resp.data


def test_legajo_empleado_muestra_fallback_si_no_tiene_foto(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
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
            "foto": None,
        },
    )
    monkeypatch.setattr(legajos_routes, "get_eventos_by_empleado", lambda emp_id, include_anulados=True: [])
    monkeypatch.setattr(legajos_routes, "get_tipos_evento", lambda include_inactive=False: [])

    resp = client.get("/legajos/empleado/7")
    assert resp.status_code == 200
    assert b"img/empleado-default.svg" in resp.data


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


def test_legajo_tipos_evento_listado(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        legajo_tipos_evento_routes,
        "get_tipos_evento_page",
        lambda **kwargs: (
            [
                {
                    "id": 1,
                    "codigo": "certificado_medico",
                    "nombre": "Certificado medico",
                    "requiere_rango_fechas": 0,
                    "permite_adjuntos": 1,
                    "activo": 1,
                }
            ],
            1,
        ),
    )

    resp = client.get("/legajos/tipos-evento/?activo=1")
    assert resp.status_code == 200
    assert b"Tipos de evento" in resp.data
    assert b"certificado_medico" in resp.data


def test_legajo_tipos_evento_nuevo(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajo_tipos_evento_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(legajo_tipos_evento_routes, "get_tipo_evento_by_codigo", lambda codigo: None)

    captured = {}

    def _fake_create_tipo_evento(data):
        captured["data"] = dict(data)
        return 51

    monkeypatch.setattr(legajo_tipos_evento_routes, "create_tipo_evento", _fake_create_tipo_evento)

    resp = client.post(
        "/legajos/tipos-evento/nuevo",
        data={
            "codigo": " Certificado  Medico ",
            "nombre": "Certificado medico",
            "requiere_rango_fechas": "1",
            "permite_adjuntos": "1",
            "activo": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/legajos/tipos-evento/")
    assert captured["data"]["codigo"] == "certificado_medico"
    assert captured["data"]["requiere_rango_fechas"] is True
    assert captured["data"]["permite_adjuntos"] is True
    assert captured["data"]["activo"] is True


def test_legajo_tipos_evento_editar(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajo_tipos_evento_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        legajo_tipos_evento_routes,
        "get_tipo_evento_by_id",
        lambda tipo_id: {
            "id": tipo_id,
            "codigo": "certificado_medico",
            "nombre": "Certificado medico",
            "requiere_rango_fechas": 0,
            "permite_adjuntos": 1,
            "activo": 1,
        },
    )
    monkeypatch.setattr(
        legajo_tipos_evento_routes,
        "get_tipo_evento_by_codigo",
        lambda codigo: {"id": 9} if codigo == "certificado_medico" else None,
    )

    captured = {}
    monkeypatch.setattr(
        legajo_tipos_evento_routes,
        "update_tipo_evento",
        lambda tipo_id, data: captured.update({"tipo_id": tipo_id, "data": dict(data)}),
    )

    resp = client.post(
        "/legajos/tipos-evento/editar/9",
        data={
            "codigo": "certificado_medico",
            "nombre": "Certificado actualizado",
            "permite_adjuntos": "1",
            "activo": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/legajos/tipos-evento/")
    assert captured["tipo_id"] == 9
    assert captured["data"]["nombre"] == "Certificado actualizado"
    assert captured["data"]["requiere_rango_fechas"] is False


def test_legajo_tipos_evento_activar_desactivar(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajo_tipos_evento_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(legajo_tipos_evento_routes, "get_tipo_evento_by_id", lambda tipo_id: {"id": tipo_id})
    monkeypatch.setattr(legajo_tipos_evento_routes, "count_eventos_vigentes_by_tipo", lambda tipo_id: 0)

    captured = []
    monkeypatch.setattr(
        legajo_tipos_evento_routes,
        "set_tipo_evento_activo",
        lambda tipo_id, activo: captured.append((tipo_id, activo)),
    )

    resp_1 = client.get("/legajos/tipos-evento/desactivar/9", follow_redirects=False)
    resp_2 = client.get("/legajos/tipos-evento/activar/9", follow_redirects=False)

    assert resp_1.status_code == 302
    assert resp_2.status_code == 302
    assert captured == [(9, 0), (9, 1)]


def test_legajo_tipos_evento_no_desactiva_con_eventos_vigentes(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(legajo_tipos_evento_routes, "get_tipo_evento_by_id", lambda tipo_id: {"id": tipo_id})
    monkeypatch.setattr(legajo_tipos_evento_routes, "count_eventos_vigentes_by_tipo", lambda tipo_id: 3)

    called = {"set": False}
    monkeypatch.setattr(
        legajo_tipos_evento_routes,
        "set_tipo_evento_activo",
        lambda tipo_id, activo: called.update({"set": True}),
    )

    resp = client.get("/legajos/tipos-evento/desactivar/9", follow_redirects=False)
    assert resp.status_code == 400
    assert b"eventos vigentes asociados" in resp.data
    assert called["set"] is False
